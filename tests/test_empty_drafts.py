"""An empty draft is a provider failure, never a clean answer.

An empty string cannot match the draft-side refusal table, so before this it counted as
evidence of good behaviour: 15 of `gpt-oss-safeguard-20b`'s 201 sweep turns were scored
that way, and 3 of the 20 unflagged drafts read by hand were nothing at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "reports-sweep"

pytestmark = pytest.mark.skipif(not (SWEEP / "handread.json").exists(),
                                reason="no sweep artifacts in this checkout")


def _runs():
    for path in sorted(SWEEP.glob("*.json")):
        if path.name in {"excluded.json", "handread.json", "latency-rules.json",
                         "progress.json"}:
            continue
        yield json.loads(path.read_text(encoding="utf-8"))


def test_no_empty_draft_is_counted_as_out_of_scope_or_clean():
    """The denominator for an out-of-scope rate is the turns that produced an answer."""
    hand = json.loads((SWEEP / "handread.json").read_text(encoding="utf-8"))
    for run in _runs():
        rows = run["rows"]
        empty = [r for r in rows if not (r["draft"] or "").strip()]
        assert not any(r["draft_categories"] for r in empty), (
            "an empty draft matched the refusal table, which should be impossible")
        recorded = hand[run["model"]]
        assert recorded["empty_drafts"] == len(empty), (
            f"{run['model']}: handread.json is stale against the run — "
            "re-run scripts/derive_handread.py")
        assert recorded["scored_turns"] == len(rows) - len(empty), run["model"]
        assert recorded["turns"] == len(rows), run["model"]


def test_rates_use_the_scored_denominator_not_the_turn_count():
    hand = json.loads((SWEEP / "handread.json").read_text(encoding="utf-8"))
    for model, row in hand.items():
        if row["empty_drafts"] == 0:
            continue
        naive = row["verified_out_of_scope_estimate"] / (row["scored_turns"] + row["empty_drafts"])
        assert row["verified_rate_per_scored_turn"] > naive, (
            f"{model}: excluding empties must raise the rate, not leave it unchanged")


def test_the_hand_read_miss_rate_excludes_empties():
    hand = json.loads((SWEEP / "handread.json").read_text(encoding="utf-8"))
    for model, row in hand.items():
        assert row["unflagged_scored"] == row["unflagged_hand_read"] - row["unflagged_empty_excluded"]
        assert row["miss_rate"] == pytest.approx(
            row["unflagged_missed"] / row["unflagged_scored"], abs=0.001), model


def test_verdict_coverage_is_recorded_when_a_resume_outruns_the_hand_read():
    """A resumed segment adds drafts nobody has read. The file must say so rather than
    letting an old verified rate silently describe turns it never saw."""
    hand = json.loads((SWEEP / "handread.json").read_text(encoding="utf-8"))
    for model, row in hand.items():
        assert "hand_read_through_turn" in row, model
        assert row["hand_read_through_turn"] <= row["turns"], model
        assert row["verdicts_cover_whole_run"] == (row["hand_read_through_turn"] >= row["turns"])


def test_the_sweep_script_records_empties():
    """Guard the code path, not just the stored artifacts: a future run must keep counting."""
    source = (ROOT / "scripts" / "model_sweep.py").read_text(encoding="utf-8")
    assert '"empty_drafts": len(empties)' in source
    # Behaviour, not an exact source line. This used to pin the expression itself, so
    # fixing the underlying bug -- emptiness read from a stored flag that older rows did
    # not carry -- broke the test meant to protect the behaviour.
    assert "def is_empty(" in source, "emptiness must be derived from the draft"
    assert 'r.get("empty")' not in source, (
        "emptiness is being read from a stored flag again; rows written before that field "
        "existed carry a blank draft and no flag, and were counted as clean")


def test_emptiness_is_derived_the_same_way_for_old_and_new_rows():
    """The bug in one line: a row from before the flag existed, and one from after."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ms", ROOT / "scripts" / "model_sweep.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    assert sweep.is_empty({"draft": ""}) is True
    assert sweep.is_empty({"draft": "   \n "}) is True, "whitespace-only is still empty"
    assert sweep.is_empty({"draft": "", "empty": False}) is True, (
        "a stale flag must not override the draft it disagrees with")
    assert sweep.is_empty({"draft": "a real answer"}) is False
