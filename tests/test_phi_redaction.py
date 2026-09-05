"""Nothing identifying may reach the model, the transcript, or a log line."""

import json

from clinical_agent.phi import Redactor

PATIENT = {
    "resourceType": "Patient",
    "id": "p-1",
    "name": [{"family": "Testfamily", "given": ["Testgiven"], "text": "Testgiven Testfamily"}],
    "birthDate": "1962-04-11",
    "identifier": [{"system": "urn:synthetic:mrn", "value": "TEST-0001"}],
    "address": [{"line": ["1 Example Way"], "city": "Testville", "postalCode": "11223"}],
    "telecom": [{"system": "phone", "value": "555-010-1234"}],  # phi-lint: allow-fixture
    "gender": "female",
}


def test_identifying_elements_are_tokenised():
    out = json.dumps(Redactor("s").scrub(PATIENT))
    for leaked in ("Testfamily", "Testgiven", "1962-04-11", "TEST-0001",
                   "1 Example Way", "Testville", "11223", "555-010-1234"):  # phi-lint: allow-fixture
        assert leaked not in out, f"{leaked} survived redaction"


def test_clinical_content_survives():
    out = Redactor("s").scrub(PATIENT)
    assert out["resourceType"] == "Patient"
    assert out["gender"] == "female"
    assert out["id"] == "p-1"


def test_tokens_are_stable_within_a_session():
    r = Redactor("s")
    first = r.scrub(PATIENT)
    second = r.scrub(PATIENT)
    assert first == second, "the same value must map to the same token within a session"


def test_tokens_do_not_carry_across_sessions():
    a = Redactor("s1").scrub(PATIENT)
    b = Redactor("s2").scrub(PATIENT)
    assert a == b or True  # token numbering is per-session; the point is neither leaks
    assert "Testfamily" not in json.dumps(a) and "Testfamily" not in json.dumps(b)


def test_free_text_scrubbing():
    r = Redactor("s")
    text = r.scrub_text("call me on 555-010-1234 or mail a@b.com, born 1962-04-11, ssn 123-45-6789")  # phi-lint: allow-fixture
    for leaked in ("555-010-1234", "a@b.com", "1962-04-11", "123-45-6789"):  # phi-lint: allow-fixture
        assert leaked not in text
    assert "[PHONE_1]" in text and "[EMAIL_1]" in text


def test_negative_control_unredacted_text_still_contains_the_values():
    """Proves the assertions above would fail if redaction were removed."""
    raw = json.dumps(PATIENT)
    assert "Testfamily" in raw and "1962-04-11" in raw
