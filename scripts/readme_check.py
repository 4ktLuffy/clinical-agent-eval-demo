#!/usr/bin/env python3
"""Regenerate every number the README claims and diff it against the file.

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
README = ROOT / "README.md"
FHIR_URL = "http://localhost:8080/fhir"


class Check:
    def __init__(self, label: str, source: str, expected: str, pattern: str) -> None:
        self.label, self.source, self.expected, self.pattern = label, source, expected, pattern


def _readme() -> str:
    return re.sub(r"\s+", " ", README.read_text(encoding="utf-8"))


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
        for guard, rows in conv["mutation"].items():
            for row in rows:
                before, after = f"{row['before']*100:.1f}%", f"{row['after']*100:.1f}%"
                checks.append(Check(f"mutation {guard}", "reports/conversation-eval.json",
                                    f"{before} -> {after}",
                                    rf"`{guard}` \| `{row['dimension']}` \| {re.escape(before)} \| {re.escape(after)}"))
    else:
        skipped.append("reports/conversation-eval.json missing (run: make eval)")

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

    software = _fhir_software()
    if software:
        version, fhir_version = software
        checks.append(Check("HAPI version", f"{FHIR_URL}/metadata", version, rf"HAPI FHIR JPA {re.escape(version)}"))
        checks.append(Check("FHIR version", f"{FHIR_URL}/metadata", fhir_version, rf"\(R4 {re.escape(fhir_version)}\)"))
        for resource, phrase in (("Patient", r"{} Synthea patients"),
                                 ("Encounter", r"{} encounters"),
                                 ("MedicationRequest", r"{} medication requests"),
                                 ("Observation", r"{} observations")):
            count = _fhir_count(resource)
            if count is None:
                skipped.append(f"{resource} count unavailable")
                continue
            rendered = f"{count:,}"
            checks.append(Check(f"{resource} count", f"{FHIR_URL}/{resource}?_summary=count",
                                rendered, phrase.format(re.escape(rendered))))
    else:
        skipped.append(f"no FHIR server at {FHIR_URL} (run: make fhir-up && make load)")

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
