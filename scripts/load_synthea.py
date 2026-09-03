#!/usr/bin/env python3
"""Load synthetic FHIR R4 transaction bundles into a HAPI FHIR JPA server.

Every record handled here is machine-generated. There is no path in this script that
reads a real patient record.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 300


def post_bundle(fhir_url: str, bundle: dict) -> tuple[bool, str]:
    body = json.dumps(bundle).encode("utf-8")
    request = urllib.request.Request(
        fhir_url,
        data=body,
        headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status < 300, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001 - the loader reports, it does not crash the run
        return False, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="load_synthea")
    parser.add_argument("--fhir-url", default="http://localhost:8080/fhir")
    parser.add_argument("--bundle-dir", type=Path, default=Path("data/synthea/fhir"))
    parser.add_argument("--limit", type=int, default=0, help="0 loads every bundle")
    args = parser.parse_args(argv)

    bundles = sorted(args.bundle_dir.glob("*.json"))
    # Synthea writes hospital and practitioner bundles alongside the patient ones; load
    # those first so patient references resolve.
    infra = [b for b in bundles if b.name.startswith(("hospitalInformation", "practitionerInformation"))]
    patients = [b for b in bundles if b not in infra]
    if args.limit:
        patients = patients[: args.limit]
    ordered = infra + patients

    if not ordered:
        print(f"no bundles found in {args.bundle_dir}", file=sys.stderr)
        return 1

    started = time.time()
    ok = failed = 0
    for index, path in enumerate(ordered, start=1):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        success, detail = post_bundle(args.fhir_url, bundle)
        if success:
            ok += 1
        else:
            failed += 1
            if failed <= 5:
                print(f"  FAILED {path.name}: {detail}", file=sys.stderr)
        if index % 25 == 0 or index == len(ordered):
            print(f"  {index}/{len(ordered)} bundles  ok={ok} failed={failed}", flush=True)

    elapsed = time.time() - started
    print(f"loaded {ok}/{len(ordered)} bundles in {elapsed:.1f}s ({failed} failed)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
