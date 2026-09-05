"""The audit log is append-only and records the attempt, not just the success."""

import json

from clinical_agent.audit import AuditEntry, AuditLog


def _entry(**over):
    base = dict(
        session_id="s1", actor="agent", patient_scope="p1", operation="read",
        resource_type="Patient", resource_id="p1", outcome="ok", detail=None,
    )
    base.update(over)
    return AuditEntry(**base)


def test_writes_one_line_per_access(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.write(_entry())
    log.write(_entry(operation="search", resource_type="MedicationRequest", resource_id=None))
    rows = log.read()
    assert len(rows) == 2
    assert rows[0]["resource_type"] == "Patient"
    assert rows[1]["operation"] == "search"


def test_appends_rather_than_rewrites(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).write(_entry())
    AuditLog(path).write(_entry(outcome="blocked"))
    assert len(AuditLog(path).read()) == 2


def test_records_the_required_fields(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    row = log.write(_entry(outcome="blocked", detail="cross-patient"))
    for field in ("ts", "session_id", "actor", "patient_scope", "operation",
                  "resource_type", "resource_id", "outcome"):
        assert field in row, field
    assert row["outcome"] == "blocked"


def test_lines_are_valid_json(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).write(_entry())
    for line in path.read_text().splitlines():
        json.loads(line)
