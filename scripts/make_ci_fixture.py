#!/usr/bin/env python3
"""Build a small committed FHIR fixture so CI can run the live tests.

The full Synthea output is 879 MB and is gitignored. CI still needs a real FHIR server
with real resources, so this trims a handful of patients down to the resource types the
agent actually reads, drops the bulk types (Observation, Claim, ExplanationOfBenefit,
DocumentReference, ImagingStudy), and writes one transaction bundle.

Deterministic: patients are taken in sorted filename order, resources in file order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The runtime Redactor replaces values with tokens like [DOB_1]. That is right for
# anything heading to a model or a log, and wrong here: this file is POSTed to a FHIR
# server, which will reject "[DOB_1]" as a date. So the fixture gets a type-preserving
# scrub instead -- still nothing PHI-shaped, but every value stays a legal FHIR value.

# What the six MCP tools read, plus what they reference.
# Exactly what the six MCP tools read. Anything else drags in references to resources
# that are not in the fixture, and HAPI rejects the whole transaction when a reference
# cannot be resolved.
KEEP = {"Patient", "Encounter", "Condition", "MedicationRequest", "Appointment"}
# Bulk types the agent never reads; these are what make the bundles enormous.
DROP = {"Observation", "Claim", "ExplanationOfBenefit", "DocumentReference",
        "ImagingStudy", "Provenance", "SupplyDelivery", "Device", "Media"}

PER_PATIENT_CAP = {"Encounter": 6, "Condition": 8, "MedicationRequest": 8}


_PATIENT_SEQ: dict[str, int] = {}

# Synthea points Encounters and MedicationRequests at practitioners and organisations by
# conditional reference ("Practitioner?identifier=..."). Those bundles are excluded from
# this fixture, and HAPI rejects the whole transaction when a conditional reference
# matches nothing. Strip them; nothing the six tools read depends on them.
_CONDITIONAL_REF_FIELDS = (
    "participant", "serviceProvider", "requester", "performer", "recorder",
    "asserter", "author", "custodian", "location", "provider", "organization",
)


def _strip_conditional_refs(value):
    """Drop any reference of the form 'Type?query=...' and the fields that carry them."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _CONDITIONAL_REF_FIELDS:
                continue
            if key == "reference" and isinstance(item, str) and "?" in item:
                return None
            cleaned = _strip_conditional_refs(item)
            if cleaned is not None:
                out[key] = cleaned
        return out
    if isinstance(value, list):
        cleaned = [_strip_conditional_refs(v) for v in value]
        return [c for c in cleaned if c not in (None, {}, [])]
    return value


def _scrub_fhir_safe(resource: dict) -> dict:
    """Remove PHI-shaped values while keeping every value a legal FHIR value.

    Synthea's data is synthetic but PHI-*shaped*: 999-xx-xxxx identifiers, 555-xxx-xxxx
    telecoms, real-looking names and addresses. None of that may be tracked, and the PHI
    lint enforces it. Clinical content -- codes, statuses, dates of encounters -- is left
    alone, because that is what the tests exercise.
    """
    if resource.get("resourceType") != "Patient":
        return resource
    rid = resource.get("id", "")
    index = _PATIENT_SEQ.setdefault(rid, len(_PATIENT_SEQ) + 1)
    scrubbed = dict(resource)
    scrubbed["name"] = [{"use": "official", "family": f"Testpatient{index:03d}",
                         "given": [f"Test{index:03d}"]}]
    scrubbed["birthDate"] = f"{1900 + index}-01-01"
    scrubbed["identifier"] = [{"system": "urn:synthetic:mrn", "value": f"TEST-{index:04d}"}]
    scrubbed["address"] = [{"city": "Testville", "country": "GB"}]
    for field in ("telecom", "photo", "contact", "communication", "maritalStatus",
                  "multipleBirthBoolean", "text", "extension"):
        scrubbed.pop(field, None)
    if "deceasedDateTime" in scrubbed:
        scrubbed["deceasedDateTime"] = f"{1990 + index}-01-01T00:00:00Z"
    return scrubbed


def _drop_dangling(value, known: set[str]):
    """Remove references to urn:uuid targets that are not present in this bundle."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if (key == "reference" and isinstance(item, str)
                    and item.startswith("urn:uuid:") and item not in known):
                return None
            cleaned = _drop_dangling(item, known)
            if cleaned is not None:
                out[key] = cleaned
        return out
    if isinstance(value, list):
        cleaned = [_drop_dangling(v, known) for v in value]
        return [c for c in cleaned if c not in (None, {}, [])]
    return value


def trim(bundle: dict) -> list[dict]:
    kept: list[dict] = []
    counts: dict[str, int] = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        kind = resource.get("resourceType")
        if kind in DROP or kind not in KEEP:
            continue
        cap = PER_PATIENT_CAP.get(kind)
        if cap is not None:
            counts[kind] = counts.get(kind, 0) + 1
            if counts[kind] > cap:
                continue
        kept.append({
            "fullUrl": entry.get("fullUrl"),
            "resource": resource,
            "request": entry.get("request", {"method": "POST", "url": kind}),
        })
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_ci_fixture")
    parser.add_argument("--bundle-dir", type=Path, default=ROOT / "data" / "synthea" / "fhir")
    parser.add_argument("--patients", type=int, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "ci-fixture" / "bundle.json")
    args = parser.parse_args(argv)

    sources = sorted(
        p for p in args.bundle_dir.glob("*.json")
        if not p.name.startswith(("hospitalInformation", "practitionerInformation"))
    )
    if len(sources) < args.patients:
        print(f"need {args.patients} bundles in {args.bundle_dir}, found {len(sources)}",
              file=sys.stderr)
        return 1

    entries: list[dict] = []
    for path in sources[: args.patients]:
        entries.extend(trim(json.loads(path.read_text(encoding="utf-8"))))

    entries = [
        {**entry, "resource": _scrub_fhir_safe(_strip_conditional_refs(entry["resource"]))}
        for entry in entries
    ]
    # Second pass: a urn:uuid reference to something not in this bundle is a placeholder
    # HAPI cannot satisfy, and it fails the entire transaction rather than that one field.
    known = {entry.get("fullUrl") for entry in entries}
    entries = [{**entry, "resource": _drop_dangling(entry["resource"], known)} for entry in entries]

    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": entries}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")

    kinds: dict[str, int] = {}
    for entry in entries:
        kind = entry["resource"]["resourceType"]
        kinds[kind] = kinds.get(kind, 0) + 1
    size_kb = args.out.stat().st_size / 1024
    print(f"wrote {args.out.relative_to(ROOT)}  {size_kb:.0f} KB  {len(entries)} resources")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind:<20} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
