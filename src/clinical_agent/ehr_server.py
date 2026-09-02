"""MCP server exposing three EHR tools over stdio.

Resources are FHIR-shaped JSON (Patient, Slot, Appointment). Shape only: no
conformance to the FHIR specification is claimed or tested.

Run as: python -m clinical_agent.ehr_server
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# The one injected failure in the whole repo. It is what gives the operational
# escalation path and the tool-error-burst anomaly rule something real to see.
FAILING_MRN = "TEST-0009"
WRITE_ERROR = "EHR write rejected: slot hold expired"


def _data_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("could not locate the data directory")


def _load(name: str) -> dict:
    return json.loads((_data_dir() / name).read_text(encoding="utf-8"))


mcp = FastMCP("synthetic-ehr")


@mcp.tool()
def patient_lookup(mrn: str) -> dict:
    """Look up a synthetic Patient resource by medical record number."""
    patients = _load("patients.json")["patients"]
    for patient in patients:
        for identifier in patient.get("identifier", []):
            if identifier.get("value") == mrn:
                return {"ok": True, "patient": patient}
    return {"ok": False, "error": f"no patient with MRN {mrn}"}


@mcp.tool()
def list_slots(specialty: str) -> dict:
    """List free synthetic Slot resources for a specialty."""
    slots = _load("appointments.json")["slots"]
    free = [s for s in slots if s.get("specialty") == specialty and s.get("status") == "free"]
    if not free:
        return {"ok": False, "error": f"no free slots for {specialty}"}
    return {"ok": True, "slots": free}


@mcp.tool()
def book_appointment(mrn: str, slot_id: str) -> dict:
    """Book a synthetic Appointment against a Slot."""
    if mrn == FAILING_MRN:
        return {"ok": False, "error": WRITE_ERROR}
    slots = {s["id"]: s for s in _load("appointments.json")["slots"]}
    if slot_id not in slots:
        return {"ok": False, "error": f"no slot {slot_id}"}
    if slots[slot_id].get("status") != "free":
        return {"ok": False, "error": f"slot {slot_id} is not free"}
    return {
        "ok": True,
        "appointment": {
            "resourceType": "Appointment",
            "id": f"appt-{slot_id}",
            "status": "booked",
            "participant": [{"actor": {"identifier": {"value": mrn}}, "status": "accepted"}],
            "slot": [{"reference": f"Slot/{slot_id}"}],
            "start": slots[slot_id]["start"],
            "end": slots[slot_id]["end"],
        },
    }


if __name__ == "__main__":
    # The server is a subprocess of the eval run; its per-request logging would
    # otherwise interleave with the scorecard on the terminal.
    logging.getLogger().setLevel(logging.WARNING)
    mcp.run()
