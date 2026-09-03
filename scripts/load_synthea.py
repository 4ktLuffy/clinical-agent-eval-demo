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


def _patient_count(fhir_url: str) -> int:
    """Patients already on the server, or 0 if it cannot be asked."""
    try:
        request = urllib.request.Request(
            f"{fhir_url}/Patient?_summary=count",
            headers={"Accept": "application/fhir+json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(json.loads(response.read()).get("total", 0))
    except Exception:  # noqa: BLE001 - an unreachable server is the caller's problem
        return 0


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
    parser.add_argument("--force", action="store_true",
                        help="load even if the server already holds patients")
    args = parser.parse_args(argv)

    # Loading is POST-per-bundle, so running it twice creates a second copy of every
    # patient rather than updating them. Nothing errors; the counts just double and every
    # downstream number is quietly wrong. Refuse instead.
    existing = _patient_count(args.fhir_url)
    if existing and not args.force:
        print(
            f"refusing to load: {args.fhir_url} already holds {existing} patients.\n"
            "  This loader POSTs, so a second run duplicates every record.\n"
            "  Use `make clean-fhir` for an empty database, or pass --force if you "
            "really mean to add another copy.",
            file=sys.stderr,
        )
        return 1

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
