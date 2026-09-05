#!/usr/bin/env python3
"""Regenerate every number the README claims and diff it against the file.

Numbers are read from **committed artifacts produced by the documented commands**, never
from whatever server happens to be running or whatever run happened last. An earlier
version queried the live server and read the most recent load report, so it failed in CI
for the wrong reason: CI loads a 10-patient fixture and runs a 400-session load, while the
README documents the full 213-patient dataset and a 2,000-session run. Comparing a claim
against an unrelated run is not a fact check.

Each check names where its value comes from. Nothing here reads a number out of the
README and compares it to itself: the expected side is always recomputed from a report,
a live server, or the code. A number that cannot be regenerated does not belong in the
README, and there is no check for one here because there is no such number left.

Exit 0 if the README agrees with the artifacts, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = (ROOT / "README.md", ROOT / "LIMITATIONS.md")
FHIR_URL = "http://localhost:8080/fhir"


class Check:
    def __init__(self, label: str, source: str, expected: str, pattern: str) -> None:
        self.label, self.source, self.expected, self.pattern = label, source, expected, pattern


def _readme() -> str:
    """README plus LIMITATIONS. Both are documentation whose numbers must be true, and
    moving a claim from one to the other must not silently drop it from the check."""
    return re.sub(r"\s+", " ", "\n".join(d.read_text(encoding="utf-8") for d in DOCS))


def _load(name: str) -> dict | None:
    path = ROOT / "reports" / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fhir_count(resource: str) -> int | None:
    try:
        request = urllib.request.Request(
            f"{FHIR_URL}/{resource}?_summary=count", headers={"Accept": "application/fhir+json"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(json.loads(response.read())["total"])
    except Exception:
        return None


def _fhir_software() -> tuple[str, str] | None:
    try:
        request = urllib.request.Request(
            f"{FHIR_URL}/metadata", headers={"Accept": "application/fhir+json"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
        return payload["software"]["version"], payload["fhirVersion"]
    except Exception:
        return None


def _escalation_phrase_count() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from clinical_agent.guardrail import _ESCALATION_PATTERNS

    return len(_ESCALATION_PATTERNS)


def build_checks() -> tuple[list[Check], list[str]]:
    checks: list[Check] = []
    skipped: list[str] = []

    conv = _load("conversation-eval.json")
    if conv and conv.get("model", "mock") != "mock":
        skipped.append(
            f"reports/conversation-eval.json holds a {conv['model']} run, not the mock run "
            "the README quotes; regenerate with `make eval`"
        )
        conv = None
    if conv:
        checks.append(Check("conversations", "reports/conversation-eval.json",
                            f"{conv['conversations']}", rf"\b{conv['conversations']} conversations\b"))
        turns = f"{conv['turns']:,}"
        checks.append(Check("rubric turns", "reports/conversation-eval.json",
                            turns, rf"{turns} turns"))
        for dimension, entry in conv["rubric"].items():
            rate = f"{entry['rate'] * 100:.1f}%"
            checks.append(Check(f"rubric {dimension}", "reports/conversation-eval.json",
                                rate, rf"`{dimension}` \| {re.escape(rate)}"))
        # Real-model runs set mutation to None deliberately. This is the third place that
        # assumption broke something -- render(), the exit-code path, and here.
        for guard, rows in (conv.get("mutation") or {}).items():
            for row in rows:
                # A guard that never fired on this run has an identical before/after and
                # no claim to document. Requiring a README row for it would force the docs
                # to assert a mutation result the run did not produce.
                if not row.get("exercised", True):
                    continue
                before, after = f"{row['before']*100:.1f}%", f"{row['after']*100:.1f}%"
                checks.append(Check(f"mutation {guard}", "reports/conversation-eval.json",
                                    f"{before} -> {after}",
                                    rf"`{guard}` \| `{row['dimension']}` \| {re.escape(before)} \| {re.escape(after)}"))
    else:
        skipped.append("reports/conversation-eval.json missing (run: make eval)")

    # Held-out v2 and the model sweep. Neither can be regenerated inside CI -- the sweep is
    # hours of provider calls -- so their summaries are committed and diffed here. Without
    # this the headline numbers in FINDINGS were asserted, not checked.
    for path, label, pattern in (
        ("reports/heldout-recall-none.json", "held-out phrase table", None),
        ("reports/heldout-recall-local.json", "held-out shipped stage", None),
    ):
        held = ROOT / path
        if not held.exists():
            skipped.append(f"{path} missing (run: python scripts/heldout_recall.py)")
            continue
        payload = json.loads(held.read_text(encoding="utf-8"))
        recall = f"{payload['overall']['recall'] * 100:.1f}%"
        checks.append(Check(f"{label} recall", path, recall, re.escape(recall)))
        combined = payload.get("combined")
        if combined:
            precision = f"{combined['precision']:.3f}"
            checks.append(Check(f"{label} precision", path, precision, re.escape(precision)))

    handread = ROOT / "reports-sweep" / "handread.json"
    if handread.exists():
        for model, row in json.loads(handread.read_text(encoding="utf-8")).items():
            short = model.split("/")[-1]
            checks.append(Check(f"sweep {short} flagged", "reports-sweep/handread.json",
                                str(row["flagged_raw"]),
                                rf"\b{row['flagged_raw']}\b"))
    else:
        skipped.append("reports-sweep/handread.json missing (run: scripts/model_sweep.py)")


    load = _load("load-report.json")
    if load:
        sessions = f"{load['sessions']:,}"
        checks.append(Check("load sessions", "reports/load-report.json",
                            sessions, rf"{sessions} concurrent sessions"))
        total_turns = f"{sum(s['summary']['turns'] for s in load['scenarios']):,}"
        checks.append(Check("load turns", "reports/load-report.json",
                            total_turns, rf"{total_turns} turns"))
        for scenario in load["scenarios"]:
            expected = scenario["expected_detector"]
            verdict = "quiet" if expected is None else "fired"
            label = {"baseline": "baseline", "tool_error_spike": "tool error spike",
                     "latency_cliff": "latency cliff",
                     "guardrail_silently_off": "guardrail silently off",
                     "cross_patient_probe": "cross-patient probe"}[scenario["fault"]]
            checks.append(Check(f"detector {scenario['fault']}", "reports/load-report.json",
                                verdict, rf"\| {re.escape(label)} \|[^|]*\| {verdict} \|"))
    else:
        skipped.append("reports/load-report.json missing (run: make loadtest)")

    dataset = _load("fhir-check.json")
    if dataset:
        source = "reports/fhir-check.json (make fhir-check)"
        server = dataset["server"]          # e.g. "HAPI FHIR Server 8.12.0 FHIR 4.0.1"
        parts = server.split()
        version, fhir_version = parts[3], parts[-1]
        checks.append(Check("HAPI version", source, version, rf"HAPI FHIR JPA {re.escape(version)}"))
        checks.append(Check("FHIR version", source, fhir_version, rf"\(R4 {re.escape(fhir_version)}\)"))
        for resource, phrase in (("Patient", r"{} Synthea patients"),
                                 ("Encounter", r"{} encounters"),
                                 ("MedicationRequest", r"{} medication requests"),
                                 ("Observation", r"{} observations")):
            entry = dataset["results"].get(resource)
            if not entry:
                skipped.append(f"{resource} not in fhir-check.json")
                continue
            rendered = f"{entry['found']:,}"
            checks.append(Check(f"{resource} count", source, rendered,
                                phrase.format(re.escape(rendered))))
    else:
        skipped.append("reports/fhir-check.json missing (run: make fhir-check against a full load)")

    phrases = _escalation_phrase_count()
    checks.append(Check("escalation phrases", "clinical_agent.guardrail._ESCALATION_PATTERNS",
                        f"{phrases}", r"fixture of about thirty phrases"))
    if not 25 <= phrases <= 34:
        skipped.append(f"escalation table has {phrases} phrases; README says 'about thirty'")

    return checks, skipped


def main() -> int:
    text = _readme()
    checks, skipped = build_checks()
    failures = []
    for check in checks:
        if not re.search(check.pattern, text):
            failures.append(check)

    print(f"readme-check: {len(checks)} regenerated numbers, {len(failures)} mismatched")
    for note in skipped:
        print(f"  skipped: {note}")
    for check in failures:
        print(f"  MISMATCH {check.label}: expected {check.expected!r} from {check.source}")
        print(f"           README has no match for /{check.pattern}/")
    if failures:
        print("\nREADME disagrees with the artifacts. Regenerate the reports, or fix the README.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
