"""MCP server over a real FHIR R4 endpoint, scoped to one patient for its whole lifetime.

The patient scope is fixed at process start from the environment. It is not a tool
parameter, so no tool call can name another patient. The single tool that accepts a
resource id re-reads that resource and refuses if it is not the session patient's.

Run as: python -m clinical_agent.fhir_mcp_server
Environment:
  CLINICAL_AGENT_FHIR_URL    base URL, e.g. http://localhost:8080/fhir
  CLINICAL_AGENT_PATIENT_ID  the only patient this process may ever touch
  CLINICAL_AGENT_SESSION_ID  correlates the audit trail
  CLINICAL_AGENT_ACTOR       who the audit trail attributes the access to
"""

from __future__ import annotations

import logging
import os

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerImpl
except ImportError:  # mcp 2.x renamed the same class
    from mcp.server.mcpserver import MCPServer as _ServerImpl

from clinical_agent.fhir_client import (
    CrossPatientAccess,
    MalformedResourceId,
    PatientScopedFhir,
)

server = _ServerImpl("scoped-fhir-ehr")


def _client() -> PatientScopedFhir:
    base = os.environ.get("CLINICAL_AGENT_FHIR_URL")
    patient = os.environ.get("CLINICAL_AGENT_PATIENT_ID")
    if not base or not patient:
        raise RuntimeError(
            "CLINICAL_AGENT_FHIR_URL and CLINICAL_AGENT_PATIENT_ID must both be set; "
            "the server refuses to start unscoped"
        )
    return PatientScopedFhir(
        base_url=base,
        patient_id=patient,
        session_id=os.environ.get("CLINICAL_AGENT_SESSION_ID", "unscoped-session"),
        actor=os.environ.get("CLINICAL_AGENT_ACTOR", "agent"),
    )


def _result(call) -> dict:
    try:
        outcome = call()
    except CrossPatientAccess as exc:
        return {"ok": False, "error": f"scope violation refused: {exc}"}
    except MalformedResourceId as exc:
        return {"ok": False, "error": f"malformed id refused: {exc}"}
    if outcome.ok:
        return {"ok": True, **(outcome.data or {})}
    return {"ok": False, "error": outcome.error}


@server.tool()
def patient_lookup() -> dict:
    """Read the session patient's demographics. Takes no patient id by design."""
    client = _client()
    return _result(client.patient_lookup)


@server.tool()
def upcoming_appointments() -> dict:
    """List the session patient's appointments, soonest first."""
    client = _client()
    return _result(client.upcoming_appointments)


@server.tool()
def active_medications() -> dict:
    """List the session patient's active medication requests."""
    client = _client()
    return _result(client.active_medications)


@server.tool()
def recent_encounters() -> dict:
    """List the session patient's most recent encounters."""
    client = _client()
    return _result(client.recent_encounters)


@server.tool()
def schedule_appointment(start: str, end: str, reason: str = "Follow-up") -> dict:
    """Create a real Appointment resource for the session patient."""
    client = _client()
    return _result(lambda: client.schedule_appointment(start, end, reason))


@server.tool()
def cancel_appointment(appointment_id: str) -> dict:
    """Cancel an appointment. Refused unless it belongs to the session patient."""
    client = _client()
    return _result(lambda: client.cancel_appointment(appointment_id))


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.WARNING)
    server.run()
