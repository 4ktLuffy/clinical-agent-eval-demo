"""Planted identifiers must never reach a report, a telemetry line, or an artifact.

The Redactor tokenises typed FHIR elements leaving the tool surface. This covers the other
boundary: free text a caller said or a model wrote, which can carry an identifier no schema
marked as one. Every assertion here is paired with a negative control, because a redaction
test that has never seen the unredacted value passes just as well when the redactor is gone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent import phi  # noqa: E402
from clinical_agent.phi import scrub_for_log  # noqa: E402

PLANTED = {
    "mrn": "MRN 40071923",
    "nhs": "NHS number 943 476 5919",
    "dob": "12/03/1954",
    "iso_dob": "1954-03-12",
    "phone_uk": "0161 496 0000",
    "phone_mobile": "07700 900123",
    "email": "a.patient@example.com",
    "ssn": "078-05-1120",
}

# Must survive untouched: clinical text that merely contains numbers.
MUST_NOT_CHANGE = [
    "take 2 tablets twice a day",
    "come back in 6 weeks",
    "your blood pressure was 130 over 80",
    "finish the 7 day course",
]


def test_every_planted_identifier_is_removed():
    for name, value in PLANTED.items():
        text = f"The caller said {value} during the call."
        assert value not in scrub_for_log(text), f"{name} survived redaction"


def test_clinical_numbers_are_not_eaten():
    """A redactor that removes every number would pass the test above and destroy the
    product. These must come through unchanged."""
    for text in MUST_NOT_CHANGE:
        assert scrub_for_log(text) == text, text


def test_redaction_reaches_nested_structures():
    row = {"turn_id": "T1", "draft": f"Call {PLANTED['phone_uk']} to confirm",
           "citations": ["c1", f"see {PLANTED['email']}"],
           "nested": {"tool_error": f"lookup failed for {PLANTED['mrn']}"}}
    cleaned = scrub_for_log(row)
    blob = json.dumps(cleaned)
    for value in (PLANTED["phone_uk"], PLANTED["email"], PLANTED["mrn"]):
        assert value not in blob, value
    assert cleaned["turn_id"] == "T1"


def test_telemetry_lines_are_redacted(tmp_path):
    from types import SimpleNamespace

    from clinical_agent.telemetry import TelemetryLog

    log = TelemetryLog(tmp_path / "telemetry.jsonl")
    decision = SimpleNamespace(refused=False, refusal_categories=(), clinical_escalation=False,
                               clinical_severity=None, clinical_system=None,
                               operational_escalation=True,
                               operational_reason=f"tool error for {PLANTED['mrn']}")
    result = SimpleNamespace(turn_id="T1", workflow="w", model="m", total_ms=1.0,
                             stage_ms={}, retrieval_top_score=0.5, used_corpus=True,
                             citations=("c1",), tool_error=f"failed {PLANTED['phone_uk']}",
                             decision=decision)
    log.record(result)
    log.close()
    written = (tmp_path / "telemetry.jsonl").read_text(encoding="utf-8")
    assert PLANTED["mrn"] not in written
    assert PLANTED["phone_uk"] not in written
    assert "[MRN]" in written and "[PHONE]" in written


def test_the_test_fails_if_the_redactor_is_removed(monkeypatch, tmp_path):
    """Negative control. Without this, every assertion above would still pass against a
    scrub_for_log that returned its input unchanged."""
    from types import SimpleNamespace

    import clinical_agent.telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module, "scrub_for_log", lambda value: value)
    log = telemetry_module.TelemetryLog(tmp_path / "t.jsonl")
    decision = SimpleNamespace(refused=False, refusal_categories=(), clinical_escalation=False,
                               clinical_severity=None, clinical_system=None,
                               operational_escalation=False, operational_reason=None)
    result = SimpleNamespace(turn_id="T1", workflow="w", model="m", total_ms=1.0,
                            stage_ms={}, retrieval_top_score=0.5, used_corpus=True,
                            citations=(), tool_error=f"failed {PLANTED['phone_uk']}",
                            decision=decision)
    log.record(result)
    log.close()
    written = (tmp_path / "t.jsonl").read_text(encoding="utf-8")
    assert PLANTED["phone_uk"] in written, (
        "the planted phone number did not appear even with redaction disabled, so the "
        "positive tests above prove nothing about the redactor"
    )


def test_committed_report_directories_carry_no_planted_identifier():
    """The artifacts actually in the repository, not a fixture. drafts.jsonl holds real
    model output, which is where an identifier would most plausibly appear."""
    offenders = []
    for directory in sorted(ROOT.glob("reports*")):
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".jsonl", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name, value in PLANTED.items():
                if value in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert not offenders, offenders


CRISIS_CASES = [
    ("please call 911 or dial 988 for the Suicide & Crisis Lifeline", True),
    ("the National Suicide Prevention Lifeline at 988.", True),
    ("call the 999 service", True),
    ("take 988 mg of paracetamol", False),
    ("in 2026 there were 911 calls logged", False),
    ("your reading was 112 over 70", False),
]


def test_crisis_numbers_are_redacted_only_in_crisis_context():
    """This repository ships no crisis number of its own, and must not ship one a model
    under test produced either: two sweep drafts offered a US lifeline to a UK service.
    Context-gated, because an ungated pattern redacted a paracetamol dose and a blood
    pressure of 112 over 70."""
    for text, should_change in CRISIS_CASES:
        changed = scrub_for_log(text) != text
        assert changed is should_change, text
    assert "[CRISIS-NUMBER]" in scrub_for_log(CRISIS_CASES[0][0])


def test_no_committed_artifact_carries_a_crisis_number():
    offenders = []
    for directory in sorted(ROOT.glob("reports*")):
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".jsonl", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for phrase in ("dial 988", "call 911", "Lifeline at 988", "call 999"):
                if phrase in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {phrase}")
    assert not offenders, offenders
