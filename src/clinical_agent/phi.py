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
# Record-number shapes a caller or a model might echo back in free text. Deliberately
# narrow: it must not eat ordinary numbers like "take 2 tablets" or "in 6 weeks".
_MRN = re.compile(
    r"\b(?:MRN|NHS(?:\s+number)?|record\s+number|patient\s+(?:id|number))\b"
    r"(?:\s+(?:is|no\.?|number|#))?[:\s#]*([A-Z]{0,3}\d[\d\s-]{4,}\d)",
    re.I)
# UK landline/mobile shapes. Anchored on a leading 0 and 10-11 digits so it cannot eat
# "take 2 tablets" or "in 6 weeks".
_UK_PHONE = re.compile(r"\b0\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b")
_UK_DOB = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")
# Crisis and emergency numbers. This repository ships none of its own -- a number that is
# wrong, stale, or wrong for the caller's country is worse than no number -- and it must not
# ship one a model under test produced either. Two sweep drafts offered a US lifeline to a
# UK service.
_CRISIS = re.compile(
    r"(?:(?<=\bcall )|(?<=\bdial )|(?<=\bcall the )|(?<=\bat )|(?<=\bring )|"
    r"(?<=\bservices \()|(?<=\bLifeline at ))"
    r"(988|911|999|112|116\s?123)\b",
    re.IGNORECASE)

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


def scrub_for_log(value: Any) -> Any:
    """Session-less redaction applied at the logging boundary, to anything about to be
    written to a report, a telemetry line or an artifact.

    The Redactor tokenises typed FHIR elements on the way OUT of the tool surface. This is
    the second boundary: free text that a model wrote, or a caller said, which can carry an
    identifier no schema marked as one. Tokens here are fixed strings rather than the
    Redactor's per-session counters, because a log line must not depend on which session
    wrote it.

    Names are not pattern-matchable and are NOT handled here. They are kept out by never
    putting an unredacted name into the prompt in the first place; this function is the
    backstop for the shapes that can be matched.
    """
    if isinstance(value, dict):
        return {k: scrub_for_log(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_for_log(v) for v in value]
    if isinstance(value, str):
        text = _CRISIS.sub("[CRISIS-NUMBER]", value)
        text = _MRN.sub("[MRN]", text)
        text = _EMAIL.sub("[EMAIL]", text)
        text = _SSN.sub("[SSN]", text)
        text = _PHONE.sub("[PHONE]", text)
        text = _UK_PHONE.sub("[PHONE]", text)
        text = _UK_DOB.sub("[DOB]", text)
        return _DATE.sub("[DATE]", text)
    return value


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
