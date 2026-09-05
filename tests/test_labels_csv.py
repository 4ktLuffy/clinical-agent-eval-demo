"""The hand-label sheet must parse, and must fail loudly rather than silently blank."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eval.run import load_labels  # noqa: E402


def test_shipped_sheet_parses_every_row_and_is_unfilled():
    """The sheet is committed blank on purpose. This asserts both that it is still blank
    and that the loader can actually see its rows -- a loader that returned nothing would
    otherwise pass the 'blank' half of this test while being completely broken."""
    labels = load_labels(ROOT / "data" / "labels_open_ended.csv")
    # 22 is the n scripts/kappa_power.py gives for the faithfulness interval to clear zero
    # at the observed point estimate. Pinned so the sheet cannot quietly shrink back below
    # the size the power calculation asked for.
    assert len(labels) == 22, f"expected 22 open-ended turns, parsed {len(labels)}"
    assert all(v == (None, None) for v in labels.values()), "sheet should ship unfilled"


def test_leading_comments_do_not_become_the_header(tmp_path):
    """The defect this guards: csv.DictReader takes its header from the first line handed
    to it, so a leading comment made every turn_id lookup return None and the sheet read
    as blank instead of as unreadable."""
    sheet = tmp_path / "s.csv"
    sheet.write_text("# a comment\n# another\nturn_id,faithfulness,citation_quality\n"
                     "T001,1.0,0.5\n", encoding="utf-8")
    assert load_labels(sheet) == {"T001": (1.0, 0.5)}


def test_blank_cells_are_none_not_zero(tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text("turn_id,faithfulness,citation_quality\nT001,,\nT002,0.0,0.0\n",
                     encoding="utf-8")
    labels = load_labels(sheet)
    assert labels["T001"] == (None, None), "a blank cell must not be read as 0.0"
    assert labels["T002"] == (0.0, 0.0)


def test_missing_turn_id_column_raises(tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="turn_id"):
        load_labels(sheet)
