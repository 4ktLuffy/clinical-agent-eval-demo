"""Patient scoping against a real FHIR server.

Skipped when no FHIR endpoint is reachable, so CI stays offline-green. Run the stack with
`make fhir-up && make synthea && make load` to exercise these.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

from clinical_agent.audit import AuditLog
from clinical_agent.fhir_client import CrossPatientAccess, PatientScopedFhir
from clinical_agent.tools import ScopedFhirTools

FHIR_URL = os.environ.get("CLINICAL_AGENT_FHIR_URL", "http://localhost:8080/fhir")


def _loaded_patients() -> int:
    """Patients on the server, or -1 if there is no server.

    Reachability alone is not enough: a server that is up but empty made these tests
    raise KeyError('entry') out of the fixture rather than skip, which reads as a broken
    test suite instead of an absent precondition.
    """
    try:
        with urllib.request.urlopen(f"{FHIR_URL}/metadata", timeout=5):
            pass
    except Exception:
        return -1
    try:
        with urllib.request.urlopen(f"{FHIR_URL}/Patient?_summary=count", timeout=10) as response:
            return int(json.loads(response.read()).get("total", 0))
    except Exception:
        return 0


_PATIENTS = _loaded_patients()
pytestmark = pytest.mark.skipif(
    _PATIENTS < 2,
    reason=(
        f"no FHIR server at {FHIR_URL}" if _PATIENTS < 0
        else f"FHIR server at {FHIR_URL} holds {_PATIENTS} patients; need at least 2 "
             "(run: make synthea && make load)"
    ),
)


@pytest.fixture(scope="module")
def two_patients() -> tuple[str, str]:
    payload = json.loads(urllib.request.urlopen(f"{FHIR_URL}/Patient?_count=2").read())
    entries = payload.get("entry", [])
    if len(entries) < 2:
        pytest.skip(f"{FHIR_URL} returned {len(entries)} patients; need 2")
    return entries[0]["resource"]["id"], entries[1]["resource"]["id"]


def test_reads_are_scoped_and_redacted(two_patients, tmp_path):
    a, _ = two_patients
    client = PatientScopedFhir(FHIR_URL, a, "t-read", audit=AuditLog(tmp_path / "a.jsonl"))
    result = client.patient_lookup()
    assert result.ok
    blob = json.dumps(result.data)
    assert "[NAME_" in blob, "patient name should be tokenised"
    assert "[DOB_" in blob, "birth date should be tokenised"


def test_no_tool_accepts_a_patient_id(two_patients):
    a, _ = two_patients
    with ScopedFhirTools(FHIR_URL, a, "t-sig") as tools:
        for name in ("patient_lookup", "upcoming_appointments",
                     "active_medications", "recent_encounters"):
            assert tools.call(name, {}).ok, name


def test_cross_patient_cancel_is_refused_and_leaves_the_resource_untouched(two_patients, tmp_path):
    a, b = two_patients
    owner = PatientScopedFhir(FHIR_URL, a, "t-owner", audit=AuditLog(tmp_path / "o.jsonl"))
    made = owner.schedule_appointment("2026-12-01T09:00:00Z", "2026-12-01T09:20:00Z")
    assert made.ok
    appointment_id = made.data["appointment"]["id"]

    attacker_audit = AuditLog(tmp_path / "attacker.jsonl")
    attacker = PatientScopedFhir(FHIR_URL, b, "t-attacker", audit=attacker_audit)
    with pytest.raises(CrossPatientAccess):
        attacker.cancel_appointment(appointment_id)

    raw = json.loads(urllib.request.urlopen(f"{FHIR_URL}/Appointment/{appointment_id}").read())
    assert raw["status"] == "booked", "the refused call must not have modified the resource"

    blocked = [r for r in attacker_audit.read() if r["outcome"] == "blocked"]
    assert blocked, "the refused attempt must be on the audit trail"
    assert blocked[-1]["patient_scope"] == b


def test_scope_violation_surfaces_through_mcp_as_an_error(two_patients):
    a, b = two_patients
    with ScopedFhirTools(FHIR_URL, a, "t-mcp-owner") as owner:
        made = owner.call("schedule_appointment",
                          {"start": "2026-12-02T09:00:00Z", "end": "2026-12-02T09:20:00Z"})
        assert made.ok
        appointment_id = made.data["appointment"]["id"]
    with ScopedFhirTools(FHIR_URL, b, "t-mcp-attacker") as attacker:
        blocked = attacker.call("cancel_appointment", {"appointment_id": appointment_id})
    assert not blocked.ok
    assert "scope violation" in blocked.error


def test_owner_can_cancel_their_own(two_patients):
    a, _ = two_patients
    with ScopedFhirTools(FHIR_URL, a, "t-own") as tools:
        made = tools.call("schedule_appointment",
                          {"start": "2026-12-03T09:00:00Z", "end": "2026-12-03T09:20:00Z"})
        cancelled = tools.call("cancel_appointment",
                               {"appointment_id": made.data["appointment"]["id"]})
    assert cancelled.ok
    assert cancelled.data["appointment"]["status"] == "cancelled"


def test_every_access_is_audited(two_patients, tmp_path):
    a, _ = two_patients
    audit = AuditLog(tmp_path / "trail.jsonl")
    client = PatientScopedFhir(FHIR_URL, a, "t-audit", actor="nurse-station-1", audit=audit)
    client.patient_lookup()
    client.active_medications()
    rows = audit.read()
    assert len(rows) == 2
    assert {r["resource_type"] for r in rows} == {"Patient", "MedicationRequest"}
    assert all(r["session_id"] == "t-audit" for r in rows)
    assert all(r["actor"] == "nurse-station-1" for r in rows)
    assert all(r["patient_scope"] == a for r in rows)
