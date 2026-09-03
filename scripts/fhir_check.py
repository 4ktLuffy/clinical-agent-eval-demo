#!/usr/bin/env python3
"""Assert the loaded FHIR dataset is the shape the agent expects.

This is the pre-traffic verification step the runbook calls for: it runs against the
customer's FHIR endpoint before any conversation is allowed near it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import urllib.error
import urllib.request

TIMEOUT_S = 60

# resource type -> minimum count the deployment needs before it is allowed to take traffic
EXPECTED = {
    "Patient": 150,
    "Encounter": 500,
    "MedicationRequest": 100,
    "Condition": 200,
    "Observation": 500,
}


def count(fhir_url: str, resource: str) -> int:
    url = f"{fhir_url}/{resource}?_summary=count"
    request = urllib.request.Request(url, headers={"Accept": "application/fhir+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return int(json.loads(response.read())["total"])


def capability(fhir_url: str) -> str:
    request = urllib.request.Request(
        f"{fhir_url}/metadata", headers={"Accept": "application/fhir+json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        payload = json.loads(response.read())
    return f"{payload.get('software', {}).get('name', '?')} " \
           f"{payload.get('software', {}).get('version', '?')} FHIR {payload.get('fhirVersion', '?')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fhir_check")
    parser.add_argument("--fhir-url", default="http://localhost:8080/fhir")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--out", type=Path, default=None,
                        help="also write the result here, as the artifact the README cites")
    args = parser.parse_args(argv)

    try:
        server = capability(args.fhir_url)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: no capability statement at {args.fhir_url}: {exc}", file=sys.stderr)
        return 1

    results, failures = {}, []
    for resource, minimum in EXPECTED.items():
        try:
            found = count(args.fhir_url, resource)
        except Exception as exc:  # noqa: BLE001
            found = -1
            failures.append(f"{resource}: query failed ({type(exc).__name__})")
        results[resource] = {"found": found, "minimum": minimum}
        if 0 <= found < minimum:
            failures.append(f"{resource}: {found} < {minimum}")

    payload = {"fhir_url": args.fhir_url, "server": server, "results": results,
               "failures": failures}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"server: {server}")
        for resource, entry in results.items():
            mark = "ok " if entry["found"] >= entry["minimum"] else "FAIL"
            print(f"  {mark} {resource:<20} {entry['found']:>7}  (need >= {entry['minimum']})")

    if failures:
        print("fhir-check FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("fhir-check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
