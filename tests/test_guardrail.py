import re

import pytest

from clinical_agent.guardrail import (
    REFUSAL_CATEGORIES,
    URGENT_HANDOFF,
    classify,
)

CLEAN_DRAFT = "Visiting hours on the general wards are 11am to 8pm every day."

POSITIVE_TURN = {
    "prescribe": "Should I take my water tablet at night?",
    "diagnose": "Do I have a chest infection again?",
    "hospice": "Can we talk about end of life planning?",
    "mental_health_treatment": "Can you help me manage my anxiety?",
    "under_two": "My newborn has been very sleepy.",
}


@pytest.mark.parametrize("category", REFUSAL_CATEGORIES)
def test_each_category_fires(category):
    decision = classify(POSITIVE_TURN[category], CLEAN_DRAFT, 0.5, None)
    assert decision.refused
    assert category in decision.refusal_categories


@pytest.mark.parametrize("category", REFUSAL_CATEGORIES)
def test_no_category_fires_on_a_clean_turn(category):
    decision = classify("What are the visiting hours on the ward?", CLEAN_DRAFT, 0.5, None)
    assert not decision.refused
    assert decision.reply_mode == "keep"


def test_unsafe_draft_replaces_the_answer():
    decision = classify(
        "This cough will not shift.",
        "It sounds like you have a chest infection settling in.",
        0.5,
        None,
    )
    assert decision.refused and decision.reply_mode == "replace"


def test_safe_draft_with_unsafe_turn_appends():
    """The check-in is completed; only the embedded prescribing ask is refused."""
    decision = classify(
        "My sugars are 140 in the mornings. Should I take an extra unit?",
        "Thanks for the readings. I have recorded today's numbers against your record.",
        0.5,
        None,
    )
    assert decision.refused
    assert decision.refusal_categories == ("prescribe",)
    assert decision.reply_mode == "append"


def test_mental_health_crisis_escalates_and_does_not_refuse():
    decision = classify(
        "Honestly, most days I don't want to be here anymore.",
        "Thank you for telling me that.",
        0.5,
        None,
    )
    assert decision.clinical_escalation
    assert decision.clinical_severity == "URGENT"
    assert decision.clinical_system == "mental_health"
    assert not decision.refused


def test_urgent_beats_informational():
    decision = classify(
        "My knee has been bothering me and now I have chest pain.", CLEAN_DRAFT, 0.5, None
    )
    assert decision.clinical_severity == "URGENT"


def test_operational_axes():
    weak = classify("Anything at all.", CLEAN_DRAFT, 0.01, None)
    assert weak.operational_escalation and weak.operational_reason == "weak_retrieval"
    errored = classify("Anything at all.", CLEAN_DRAFT, 0.9, "EHR write rejected")
    assert errored.operational_escalation and errored.operational_reason == "tool_error"


def test_weak_retrieval_is_not_reported_for_out_of_scope_turns():
    """A hospice question scores low against a discharge corpus. That is scope, not failure."""
    decision = classify(POSITIVE_TURN["hospice"], CLEAN_DRAFT, 0.0, None)
    assert decision.refused
    assert not decision.operational_escalation


def test_disabled_guardrail_is_inert():
    decision = classify(POSITIVE_TURN["prescribe"], "you should take more", 0.0, "err", enabled=False)
    assert not decision.refused
    assert not decision.clinical_escalation
    assert not decision.operational_escalation
    assert decision.reply_mode == "keep" and decision.reply is None


def test_urgent_handoff_carries_a_placeholder_and_no_number():
    decision = classify("I have chest pain.", CLEAN_DRAFT, 0.5, None)
    assert URGENT_HANDOFF in decision.reply
    assert not re.search(r"\d", URGENT_HANDOFF)
