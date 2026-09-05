"""The seam is a real subprocess, so these are real round trips over stdio."""

import pytest

from clinical_agent.ehr_server import FAILING_MRN, WRITE_ERROR
from clinical_agent.tools import EHRTools


@pytest.fixture(scope="module")
def ehr():
    with EHRTools() as tools:
        yield tools


def test_patient_lookup(ehr):
    result = ehr.patient_lookup("TEST-0001")
    assert result.ok
    assert result.data["patient"]["identifier"][0]["value"] == "TEST-0001"


def test_list_slots(ehr):
    result = ehr.list_slots("primary-care")
    assert result.ok
    assert result.data["slots"]
    assert all(s["specialty"] == "primary-care" for s in result.data["slots"])


def test_book_appointment_succeeds(ehr):
    result = ehr.book_appointment("TEST-0001", "slot-001")
    assert result.ok
    assert result.data["appointment"]["status"] == "booked"


def test_injected_write_failure(ehr):
    result = ehr.book_appointment(FAILING_MRN, "slot-003")
    assert not result.ok
    assert result.error == WRITE_ERROR


def test_unknown_patient_returns_a_result_rather_than_raising(ehr):
    result = ehr.patient_lookup("TEST-9999")
    assert not result.ok
    assert result.error


def test_unknown_tool_is_handled(ehr):
    result = ehr.call("drop_database", {})
    assert not result.ok
    assert "unknown tool" in result.error
