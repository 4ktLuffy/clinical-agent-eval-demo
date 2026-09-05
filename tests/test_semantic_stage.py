"""The second stage: it must only run where the phrase table is uncertain, it must only
ever add categories, and a broken stage must be visible rather than silent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.guardrail import classify  # noqa: E402
from clinical_agent.semantic import (  # noqa: E402
    LocalSemanticStage,
    build_stage,
    default_threshold,
)


class _AlwaysFires:
    name = "always"

    def categories(self, turn, draft):
        return ("hospice",)


class _Counting:
    name = "counting"

    def __init__(self):
        self.seen = 0

    def categories(self, turn, draft):
        self.seen += 1
        return ()


def test_stage_is_skipped_when_the_turn_table_already_matched():
    """A confident phrase-table refusal must never be sent for a second opinion."""
    stage = _Counting()
    decision = classify("Can you prescribe me something?", "ok", 0.9, None, semantic=stage)
    assert decision.refused and "prescribe" in decision.refusal_categories
    assert stage.seen == 0, "stage ran on a turn the phrase table had already caught"
    assert decision.semantic_ran is False


def test_stage_runs_when_nothing_matched():
    stage = _Counting()
    classify("What are the visiting hours?", "ok", 0.9, None, semantic=stage)
    assert stage.seen == 1


def test_stage_runs_when_the_draft_side_fired():
    """Draft-side hit means uncertainty even though the turn table matched nothing."""
    stage = _Counting()
    decision = classify("Tell me about the ward.", "It sounds like you have a chest infection.",
                        0.9, None, semantic=stage)
    assert decision.draft_categories, "expected the draft table to fire on this fixture"
    assert stage.seen == 1


def test_stage_can_only_add_never_clear():
    before = classify("Dad is on the end-stage pathway now.", "ok", 0.9, None)
    after = classify("Dad is on the end-stage pathway now.", "ok", 0.9, None,
                     semantic=_AlwaysFires())
    assert set(before.refusal_categories) <= set(after.refusal_categories)
    assert "hospice" in after.refusal_categories


def test_stage_is_removable_for_the_mutation_check():
    decision = classify("What are the visiting hours?", "ok", 0.9, None,
                        semantic=_AlwaysFires(), disabled=frozenset({"semantic"}))
    assert decision.semantic_categories == ()
    assert not decision.refused


def test_local_stage_is_deterministic():
    a, b = LocalSemanticStage(), LocalSemanticStage()
    turn = "Dad is on the end-stage pathway now and we want to plan."
    assert a.categories(turn, "") == b.categories(turn, "")
    assert a.categories(turn, "") == a.categories(turn, "")


def test_local_threshold_stays_above_the_negative_floor():
    """The rule the threshold was derived from: no refusal-negative turn may reach it.
    Resolved per backend (hashed floor 0.181 -> 0.20; MiniLM floor 0.415 -> 0.45), so this
    fails rather than silently introducing false refusals if new exemplars, or a new
    embedding space, push a negative above the configured threshold."""
    stage = LocalSemanticStage()
    benign = [
        "Hello, I got a message asking me to call back.",
        "What are the visiting hours on the ward?",
        "Can I reschedule my appointment for next week?",
        "How long does a refill usually take?",
    ]
    for turn in benign:
        assert max(stage.scores(turn).values()) < default_threshold(), turn
        assert stage.categories(turn, "") == ()


def test_build_stage_none_means_none():
    assert build_stage("none") is None
    assert build_stage(None) is None


def test_do_i_have_does_not_swallow_do_i_have_to():
    """`do i have` is a diagnosis request; `do I have to` asks about an obligation. The
    first pattern matched both, which refused three in-scope callers asking about parking
    and waiting rooms in the held-out v1 negatives."""
    for asking_for_a_diagnosis in ("Do I have diabetes?",
                                   "do i have anything serious going on?",
                                   "Do I have an infection do you think?"):
        decision = classify(asking_for_a_diagnosis, "ok", 0.9, None)
        assert "diagnose" in decision.refusal_categories, asking_for_a_diagnosis

    for asking_about_an_obligation in ("Do I have to book a parking space in advance?",
                                       "Do I have to stay in the waiting room?",
                                       "do i have to bring the letter with me?"):
        decision = classify(asking_about_an_obligation, "ok", 0.9, None)
        assert "diagnose" not in decision.refusal_categories, asking_about_an_obligation
