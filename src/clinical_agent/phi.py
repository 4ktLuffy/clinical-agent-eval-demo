"""PHI redaction. Nothing reaches the model, the transcript or a log line un-redacted.

The data in this repository is synthetic, so there is no real PHI to protect here. The
layer exists because the deployment it stands in for would carry real records, and a
redaction boundary that is added later is a redaction boundary that leaks in the meantime.

Tokens are stable within a session, so an agent can still say "your appointment on
[DATE_2]" and mean something, but nothing identifying crosses the boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,2}[-. ])?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# FHIR element names whose values are identifying regardless of content.
IDENTIFYING_KEYS = {
    "name", "family", "given", "prefix", "suffix", "text",
    "birthDate", "deceasedDateTime", "address", "line", "city", "district",
    "postalCode", "telecom", "value", "identifier", "photo", "contact",
    "maritalStatus", "communication",
}
# Keys whose values are clinically necessary and safe to keep.
CLINICAL_KEYS = {
    "resourceType", "id", "status", "intent", "code", "coding", "display", "system",
    "class", "type", "category", "medicationCodeableConcept", "reasonCode",
    "period", "start", "end", "occurrenceDateTime", "authoredOn", "clinicalStatus",
    "verificationStatus", "onsetDateTime", "abatementDateTime", "description",
    "serviceType", "specialty", "participant", "actor", "reference", "total", "entry",
    "resource", "link", "relation", "url", "fullUrl", "meta", "versionId",
    "lastUpdated", "dosageInstruction", "timing", "repeat", "frequency", "periodUnit",
    "doseAndRate", "doseQuantity", "unit", "valueQuantity", "effectiveDateTime",
    "issued", "interpretation", "referenceRange", "low", "high", "component",
}


@dataclass
class Redactor:
    """Session-scoped. The token map never leaves the process and is never logged."""

    session_id: str
    _tokens: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def token(self, kind: str, value: str) -> str:
        key = f"{kind}:{value}"
        if key not in self._tokens:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            self._tokens[key] = f"[{kind}_{self._counters[kind]}]"
        return self._tokens[key]

    def scrub_text(self, text: str) -> str:
        """Free-text pass, for anything that is not a typed FHIR element."""
        text = _SSN.sub(lambda m: self.token("SSN", m.group(0)), text)
        text = _EMAIL.sub(lambda m: self.token("EMAIL", m.group(0)), text)
        text = _PHONE.sub(lambda m: self.token("PHONE", m.group(0)), text)
        text = _DATE.sub(lambda m: self.token("DATE", m.group(0)), text)
        return text

    def scrub(self, value: Any, key: str | None = None) -> Any:
        """Walk a FHIR resource, replacing identifying elements with stable tokens."""
        if isinstance(value, dict):
            return {k: self.scrub(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub(v, key) for v in value]
        if isinstance(value, str):
            if key in IDENTIFYING_KEYS and key not in ("value",):
                return self.token(_kind_for(key), value)
            if key == "value":
                # identifier.value and telecom.value are both identifying
                return self.token("ID", value)
            return self.scrub_text(value)
        return value


def _kind_for(key: str) -> str:
    if key in ("birthDate", "deceasedDateTime"):
        return "DOB"
    if key in ("address", "line", "city", "district", "postalCode"):
        return "ADDRESS"
    if key in ("name", "family", "given", "prefix", "suffix", "text"):
        return "NAME"
    if key == "telecom":
        return "CONTACT"
    if key == "identifier":
        return "MRN"
    return "REDACTED"
