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
        assert recorded["empty_drafts"] == len(empty), run["model"]
        assert recorded["scored_turns"] == len(rows) - len(empty), run["model"]


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


def test_the_sweep_script_records_empties():
    """Guard the code path, not just the stored artifacts: a future run must keep counting."""
    source = (ROOT / "scripts" / "model_sweep.py").read_text(encoding="utf-8")
    assert '"empty": empty' in source
    assert '"empty_drafts": len(empties)' in source
    assert 'scored_rows = [r for r in rows if not r.get("empty")]' in source
