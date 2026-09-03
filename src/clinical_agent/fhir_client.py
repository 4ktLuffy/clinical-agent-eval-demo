"""Patient-scoped FHIR R4 client.

The scope is a property of the object, not an argument to its methods. A caller cannot
name another patient because no method takes a patient id. The one method that accepts a
resource id -- cancel_appointment -- re-reads the resource and verifies it belongs to the
session patient before touching it.

Every call is audited and every response is redacted before it is returned.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from clinical_agent.audit import AuditEntry, AuditLog
from clinical_agent.phi import Redactor

TIMEOUT_S = 30


# FHIR ids are [A-Za-z0-9-.]{1,64} (R4 §2.23.1). Anything else in an id position is an
# attempt to reach a different path, not a typo: "1/../Patient/2", "1?_id=2", an encoded
# slash. Validated before the value is ever interpolated into a URL.
_FHIR_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CrossPatientAccess(Exception):
    """Raised when a call would touch a resource outside the session's patient scope."""


class MalformedResourceId(Exception):
    """Raised when an id argument is not a bare FHIR id."""


@dataclass(frozen=True)
class FhirResult:
    ok: bool
    data: dict | None
    error: str | None


class PatientScopedFhir:
    def __init__(
        self,
        base_url: str,
        patient_id: str,
        session_id: str,
        actor: str = "agent",
        audit: AuditLog | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.patient_id = patient_id
        self.session_id = session_id
        self.actor = actor
        self.audit = audit or AuditLog()
        self.redactor = Redactor(session_id)

    # -- plumbing ---------------------------------------------------------------

    def _record(self, operation: str, resource_type: str, resource_id: str | None,
                outcome: str, detail: str | None = None) -> None:
        self.audit.write(
            AuditEntry(
                session_id=self.session_id,
                actor=self.actor,
                patient_scope=self.patient_id,
                operation=operation,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                detail=detail,
            )
        )

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/fhir+json",
                **({"Content-Type": "application/fhir+json"} if data else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}

    def _search(self, resource_type: str, params: dict[str, str], operation: str) -> FhirResult:
        # The patient filter is injected here, not supplied by the caller.
        params = {**params, "patient": f"Patient/{self.patient_id}"}
        query = urllib.parse.urlencode(params)
        try:
            payload = self._request("GET", f"{resource_type}?{query}")
        except Exception as exc:  # noqa: BLE001
            self._record(operation, resource_type, None, "error", f"{type(exc).__name__}")
            return FhirResult(False, None, f"{type(exc).__name__}: {exc}")
        entries = [e.get("resource", {}) for e in payload.get("entry", [])]
        leaked = self._foreign(entries)
        if leaked:
            self._record(operation, resource_type, None, "blocked", "cross-patient in result set")
            return FhirResult(False, None, f"blocked: result set referenced {leaked}")
        self._record(operation, resource_type, None, "ok", f"{len(entries)} resources")
        return FhirResult(True, {"resources": self.redactor.scrub(entries)}, None)

    def _foreign(self, resources: list[dict]) -> str | None:
        """Defence in depth: verify every returned resource really is the session patient's."""
        mine = {f"Patient/{self.patient_id}", self.patient_id}
        for resource in resources:
            for field in ("subject", "patient"):
                ref = (resource.get(field) or {}).get("reference")
                if ref and ref not in mine and ref.split("/")[-1] != self.patient_id:
                    return ref
        return None

    # -- tools ------------------------------------------------------------------

    def patient_lookup(self) -> FhirResult:
        try:
            payload = self._request("GET", f"Patient/{self.patient_id}")
        except Exception as exc:  # noqa: BLE001
            self._record("read", "Patient", self.patient_id, "error", type(exc).__name__)
            return FhirResult(False, None, f"{type(exc).__name__}: {exc}")
        self._record("read", "Patient", self.patient_id, "ok")
        return FhirResult(True, {"patient": self.redactor.scrub(payload)}, None)

    def upcoming_appointments(self) -> FhirResult:
        return self._search("Appointment", {"_sort": "date", "_count": "20"}, "search")

    def active_medications(self) -> FhirResult:
        return self._search(
            "MedicationRequest", {"status": "active", "_count": "50"}, "search"
        )

    def recent_encounters(self) -> FhirResult:
        return self._search("Encounter", {"_sort": "-date", "_count": "10"}, "search")

    def schedule_appointment(self, start: str, end: str, reason: str = "Follow-up") -> FhirResult:
        appointment = {
            "resourceType": "Appointment",
            "status": "booked",
            "description": reason,
            "start": start,
            "end": end,
            "participant": [
                {
                    "actor": {"reference": f"Patient/{self.patient_id}"},
                    "status": "accepted",
                }
            ],
        }
        try:
            created = self._request("POST", "Appointment", appointment)
        except Exception as exc:  # noqa: BLE001
            self._record("create", "Appointment", None, "error", type(exc).__name__)
            return FhirResult(False, None, f"{type(exc).__name__}: {exc}")
        self._record("create", "Appointment", created.get("id"), "ok")
        return FhirResult(True, {"appointment": self.redactor.scrub(created)}, None)

    def cancel_appointment(self, appointment_id: str) -> FhirResult:
        """The only method taking a resource id, so it is the only one that can be aimed
        at another patient. It re-reads the resource and refuses if the scope does not match."""
        decoded = urllib.parse.unquote(urllib.parse.unquote(appointment_id or ""))
        if not _FHIR_ID.match(decoded) or decoded != appointment_id:
            self._record("cancel", "Appointment", None, "blocked",
                         "malformed resource id rejected before any request")
            raise MalformedResourceId(
                f"{appointment_id!r} is not a bare FHIR id; refused without contacting the server"
            )
        try:
            existing = self._request("GET", f"Appointment/{appointment_id}")
        except urllib.error.HTTPError as exc:
            self._record("read", "Appointment", appointment_id, "error", f"HTTP {exc.code}")
            return FhirResult(False, None, f"HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            self._record("read", "Appointment", appointment_id, "error", type(exc).__name__)
            return FhirResult(False, None, f"{type(exc).__name__}: {exc}")

        owners = {
            (p.get("actor") or {}).get("reference")
            for p in existing.get("participant", [])
        }
        if f"Patient/{self.patient_id}" not in owners:
            self._record(
                "cancel", "Appointment", appointment_id, "blocked",
                "appointment belongs to another patient",
            )
            raise CrossPatientAccess(
                f"Appointment/{appointment_id} is outside the session patient scope"
            )

        existing["status"] = "cancelled"
        try:
            updated = self._request("PUT", f"Appointment/{appointment_id}", existing)
        except Exception as exc:  # noqa: BLE001
            self._record("cancel", "Appointment", appointment_id, "error", type(exc).__name__)
            return FhirResult(False, None, f"{type(exc).__name__}: {exc}")
        self._record("cancel", "Appointment", appointment_id, "ok")
        return FhirResult(True, {"appointment": self.redactor.scrub(updated)}, None)
