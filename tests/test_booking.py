"""Booking is verified against the server, not against a 201.

Two claims that are easy to confuse and must be kept apart: the server accepted a create,
and the resource is actually there. Only the second is worth telling a patient. And a
double booking must be refused by the SERVER -- an in-process check passes here and fails
the moment a second replica exists.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from clinical_agent.fhir_client import PatientScopedFhir

FHIR_URL = os.environ.get("CLINICAL_AGENT_FHIR_URL", "http://localhost:8080/fhir")


def _patients() -> int:
    try:
        with urllib.request.urlopen(f"{FHIR_URL}/metadata", timeout=5):
            pass
    except Exception:
        return -1
    try:
        with urllib.request.urlopen(f"{FHIR_URL}/Patient?_summary=count", timeout=10) as r:
            return int(json.loads(r.read()).get("total", 0))
    except Exception:
        return 0


pytestmark = pytest.mark.skipif(_patients() <= 0, reason="no loaded FHIR server")


@pytest.fixture
def client() -> PatientScopedFhir:
    probe = PatientScopedFhir(base_url=FHIR_URL, patient_id="unset", session_id="test")
    bundle = probe._request("GET", "Patient?_count=1")
    patient_id = bundle["entry"][0]["resource"]["id"]
    return PatientScopedFhir(base_url=FHIR_URL, patient_id=patient_id, session_id="test")


def _free_slot(client: PatientScopedFhir) -> tuple[str, str]:
    schedule = client._request("POST", "Schedule", {
        "resourceType": "Schedule", "active": True,
        "actor": [{"reference": f"Patient/{client.patient_id}"}]})
    start = datetime.now(timezone.utc) + timedelta(days=30)
    slot = client._request("POST", "Slot", {
        "resourceType": "Slot", "status": "free",
        "schedule": {"reference": f"Schedule/{schedule['id']}"},
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": (start + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")})
    _, headers = client._request("GET", f"Slot/{slot['id']}", want_headers=True)
    return slot["id"], headers.get("ETag")


def test_a_booking_is_confirmed_by_reading_it_back(client):
    slot_id, _ = _free_slot(client)
    result = client.book_slot(slot_id)
    assert result.ok, result.error
    assert result.data["confirmed_by_read_back"] is True
    appointment = result.data["appointment"]
    assert appointment["status"] == "booked"
    assert f"Slot/{slot_id}" in {ref["reference"] for ref in appointment.get("slot", [])}


def test_the_server_refuses_the_second_booker_not_us(client):
    """The stale ETag bypasses our own freshness check on purpose. If this passes only
    because of that check, it proves nothing about what happens under real concurrency."""
    slot_id, etag = _free_slot(client)
    assert client.book_slot(slot_id).ok

    second = client.book_slot(slot_id, known_etag=etag)
    assert not second.ok
    assert "server said" in second.error, (
        f"expected a server rejection, got {second.error!r} -- which means our own "
        "pre-check refused it and the server was never asked"
    )
    assert "409" in second.error or "412" in second.error


def test_a_tool_failure_escalates_after_one_retry():
    """One retry, then the error itself is what escalates. An escalation that loses the
    error tells on-call that something broke and not what."""
    broken = PatientScopedFhir(base_url="http://127.0.0.1:9/fhir",
                               patient_id="p", session_id="test")
    attempts, last = 0, None
    for _ in range(2):
        attempts += 1
        outcome = broken.list_slots()
        if outcome.ok:
            break
        last = outcome.error
    assert attempts == 2, "exactly one retry"
    assert last and "Error" in last
