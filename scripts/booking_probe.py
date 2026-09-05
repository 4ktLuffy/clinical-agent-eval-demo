"""End-to-end booking, verified against the server rather than against a 201.

Four things are counted:
  attempted   bookings started
  confirmed   the Appointment read back by id, booked, referencing the slot
  rejected    a second booker refused BY THE SERVER on a slot already taken
  escalated   a tool failure that survived one retry and became an operational escalation

Creates its own Slot resources so the run is repeatable and touches nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.fhir_client import PatientScopedFhir  # noqa: E402


def make_slots(client: PatientScopedFhir, count: int) -> list[str]:
    schedule = client._request("POST", "Schedule", {
        "resourceType": "Schedule", "active": True,
        "serviceType": [{"text": "General practice"}],
        "actor": [{"reference": f"Patient/{client.patient_id}"}]})
    ids = []
    base = datetime.now(timezone.utc) + timedelta(days=7)
    for i in range(count):
        start = base + timedelta(hours=i)
        created = client._request("POST", "Slot", {
            "resourceType": "Slot", "status": "free",
            "schedule": {"reference": f"Schedule/{schedule['id']}"},
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": (start + timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
            "comment": f"probe-{uuid.uuid4().hex[:8]}"})
        ids.append(created["id"])
    return ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fhir-url", default="http://localhost:8080/fhir")
    parser.add_argument("--bookings", type=int, default=5)
    parser.add_argument("--out", type=Path, default=ROOT / "reports-booking")
    args = parser.parse_args(argv)

    probe = PatientScopedFhir(base_url=args.fhir_url, patient_id="unset", session_id="probe")
    bundle = probe._request("GET", "Patient?_count=1")
    patient_id = bundle["entry"][0]["resource"]["id"]
    client = PatientScopedFhir(base_url=args.fhir_url, patient_id=patient_id, session_id="probe")

    slots = make_slots(client, args.bookings)
    # Each slot's version BEFORE anything books it: the second booker's view of the world,
    # correct when read and stale by the time it is used.
    stale_etags = {}
    for slot_id in slots:
        _, headers = client._request("GET", f"Slot/{slot_id}", want_headers=True)
        stale_etags[slot_id] = headers.get("ETag")
    rows = []
    attempted = confirmed = rejected = escalated = 0

    for slot_id in slots:
        attempted += 1
        result = client.book_slot(slot_id)
        rows.append({"slot": slot_id, "phase": "first", "ok": result.ok,
                     "confirmed": bool(result.data and result.data.get("confirmed_by_read_back")),
                     "error": result.error})
        confirmed += int(bool(result.data and result.data.get("confirmed_by_read_back")))

        # The real race: a second booker holding the version read BEFORE the first
        # booking. Its If-Match is stale, so HAPI must refuse. Passing the stale ETag
        # deliberately bypasses our own freshness check -- otherwise this would only prove
        # that our pre-check works, and nothing at all about the server.
        second = client.book_slot(slot_id, known_etag=stale_etags[slot_id])
        server_said_no = (not second.ok) and "server said" in (second.error or "")
        rejected += int(server_said_no)
        rows.append({"slot": slot_id, "phase": "double-book", "ok": second.ok,
                     "confirmed": False, "error": second.error,
                     "rejected_by_server": server_said_no})

    # Tool failure: one retry, then operational escalation carrying the error.
    broken = PatientScopedFhir(base_url="http://127.0.0.1:9/fhir", patient_id=patient_id, session_id="probe")
    attempts, last_error = 0, None
    for _ in range(2):  # the call, then exactly one retry
        attempts += 1
        outcome = broken.list_slots()
        if outcome.ok:
            break
        last_error = outcome.error
    if last_error is not None:
        escalated = 1
    rows.append({"slot": None, "phase": "tool-failure", "ok": False, "confirmed": False,
                 "error": last_error, "attempts": attempts})

    report = {
        "run_date": date.today().isoformat(), "patient_scope": "one patient, fixed at start",
        "attempted": attempted, "confirmed_by_read_back": confirmed,
        "rejected_by_server": rejected, "escalated": escalated,
        "retry_attempts_before_escalation": attempts,
        "escalation_error_recorded": last_error is not None,
        "rows": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "booking.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"attempted {attempted}  confirmed-by-re-read {confirmed}  "
          f"rejected-by-server {rejected}  escalated {escalated} "
          f"(after {attempts} attempts, error recorded: {last_error is not None})")
    return 0 if confirmed == attempted and rejected == attempted else 1


if __name__ == "__main__":
    sys.exit(main())
