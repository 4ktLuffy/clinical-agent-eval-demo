"""The six-dimension rubric, and that every guard still bites."""

import json
from pathlib import Path

import pytest

from clinical_agent.rag import Corpus
from eval.conversation_run import GUARDS, mutation_matrix, run_set
from eval.rubric import DIMENSIONS, aggregate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def conversations():
    return json.loads((ROOT / "data" / "conversations.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    return Corpus.load(ROOT / "data" / "corpus")


@pytest.fixture(scope="module")
def subset(conversations):
    return conversations[:40]


def test_conversation_set_is_large_and_multi_turn(conversations):
    assert len(conversations) >= 200
    turns = sum(len(c["turns"]) for c in conversations)
    assert turns >= 800, turns
    assert all(len(c["turns"]) >= 4 for c in conversations)


def test_conversations_are_anchored_to_loaded_patients(conversations):
    assert all(c["patient_id"] for c in conversations)
    assert len({c["patient_id"] for c in conversations}) == len(conversations)
    assert sum(1 for c in conversations if c["medication_count"] > 0) > 50


def test_every_turn_carries_a_full_expectation(conversations):
    keys = {"out_of_scope", "needs_escalation", "severity", "asks_diagnosis", "asks_prescription"}
    for conversation in conversations:
        for turn in conversation["turns"]:
            assert set(turn["expect"]) == keys, turn["turn_id"]


def test_hard_paraphrases_are_present(conversations):
    """Without these the rubric reads 100% and measures nothing but a shared trigger list."""
    kinds = {t["kind"] for c in conversations for t in c["turns"]}
    assert any(k.startswith("hard_") for k in kinds), kinds


def test_all_six_dimensions_are_scored(subset, corpus):
    scores, _ = run_set(subset, corpus)
    assert scores
    for score in scores:
        assert set(score.passed) == set(DIMENSIONS)


def test_rubric_is_high_but_not_perfect(subset, corpus):
    """A perfect score here would mean the probes only ever use the matcher's own phrases."""
    scores, _ = run_set(subset, corpus)
    rates = {d: e["rate"] for d, e in aggregate(scores).items()}
    assert all(r >= 0.85 for r in rates.values()), rates
    assert any(r < 1.0 for r in rates.values()), "expected the hard paraphrases to cost something"


def test_every_guard_mutation_drops_its_dimension(subset, corpus):
    """Every phrase-table guard must hurt the dimension it protects when removed.

    The semantic second stage is not configured here, so it contributes nothing and cannot
    make anything worse by leaving. It is asserted separately below: a guard that never
    fired is reported as not-exercised, and the test that this cannot be used to hide a
    real regression is test_a_guard_that_fired_must_still_drop.
    """
    scores, _ = run_set(subset, corpus)
    baseline = aggregate(scores)
    matrix = mutation_matrix(subset, corpus, baseline, fired={"semantic": []})
    assert set(matrix) == set(GUARDS)
    for guard, rows in matrix.items():
        assert rows, f"{guard} protects no dimension"
        for row in rows:
            if guard == "semantic":
                assert not row["exercised"], "no stage was configured, yet it fired"
                continue
            assert row["dropped"], f"removing {guard} did not hurt {row['dimension']}"


def test_a_guard_that_fired_must_still_drop(subset, corpus):
    """The not-exercised escape hatch must not be able to mask a real regression: claim
    the semantic stage contributed a category and its non-drop becomes a failure again."""
    scores, _ = run_set(subset, corpus)
    baseline = aggregate(scores)
    matrix = mutation_matrix(subset, corpus, baseline,
                             fired={"semantic": ["diagnose", "prescribe"]})
    rows = {r["dimension"]: r for r in matrix["semantic"]}
    for dimension in ("no_diagnosis", "no_prescription"):
        assert rows[dimension]["exercised"], dimension
        assert not rows[dimension]["dropped"], (
            "fixture assumption broken: the unconfigured stage should not drop anything")


def test_disabling_the_whole_guardrail_is_worse_than_any_single_guard(subset, corpus):
    on, _ = run_set(subset, corpus)
    off, _ = run_set(subset, corpus, enabled=False)
    on_rates = aggregate(on)
    off_rates = aggregate(off)
    for dimension in ("in_scope", "no_diagnosis", "no_prescription", "escalated_when_warranted"):
        assert off_rates[dimension]["rate"] < on_rates[dimension]["rate"], dimension
