"""Applying a review must be idempotent, additive, and logged.

Tested against a synthetic fixture, because the real review has not landed. A script that
first runs on the reviewer's only copy of their work is not a script anyone should trust.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "held.json"
    path.write_text(json.dumps({
        "reviewed": False, "registers": ["colloquial"],
        "categories": {
            "hospice": [{"text": "dad is on the end-stage pathway", "register": "colloquial"},
                        {"text": "where do I park at the hospice", "register": "colloquial",
                         "note": "strike: not asking"}],
            "under_two": [{"text": "my baby has a rash", "register": "colloquial",
                           "note": "relabel: hospice"}],
        },
        "negatives": {"hospice": [], "under_two": []},
    }, indent=2), encoding="utf-8")
    return path


def _run(path: Path, log: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "apply_review.py"),
         "--path", str(path), "--log", str(log), *extra],
        capture_output=True, text=True, cwd=ROOT)


def test_a_strike_marks_and_never_deletes(tmp_path):
    path, log = _fixture(tmp_path), tmp_path / "log.json"
    assert _run(path, log).returncode == 0
    data = json.loads(path.read_text())
    hospice = data["categories"]["hospice"]
    # Three: the two it started with, plus the line relabelled in from under_two.
    assert len(hospice) == 3, "a struck line must stay in the file"
    assert any(r["text"].startswith("where do I park") and r.get("struck") == "not asking"
               for r in hospice)


def test_two_adjacent_relabels_are_both_applied(tmp_path):
    """Removing from a list while iterating it skips the next element, so the second of
    two neighbouring relabels was silently left behind."""
    path, log = tmp_path / "held.json", tmp_path / "log.json"
    path.write_text(json.dumps({
        "reviewed": False, "registers": ["colloquial"],
        "categories": {
            "hospice": [],
            "under_two": [{"text": "first", "register": "colloquial", "note": "relabel: hospice"},
                          {"text": "second", "register": "colloquial", "note": "relabel: hospice"}],
        },
        "negatives": {"hospice": [], "under_two": []}}), encoding="utf-8")
    _run(path, log)
    data = json.loads(path.read_text())
    assert data["categories"]["under_two"] == [], "one relabel was skipped"
    assert len(data["categories"]["hospice"]) == 2


def test_a_relabel_moves_the_line(tmp_path):
    path, log = _fixture(tmp_path), tmp_path / "log.json"
    _run(path, log)
    data = json.loads(path.read_text())
    assert data["categories"]["under_two"] == []
    moved = [r for r in data["categories"]["hospice"] if r.get("relabelled_from")]
    assert len(moved) == 1 and moved[0]["relabelled_from"] == "under_two"


def test_running_twice_changes_nothing(tmp_path):
    path, log = _fixture(tmp_path), tmp_path / "log.json"
    _run(path, log)
    first = path.read_text()
    second_run = _run(path, log)
    assert second_run.returncode == 0
    assert path.read_text() == first, "second application drifted the set"


def test_the_reviewed_flag_and_strike_counts_are_written(tmp_path):
    path, log = _fixture(tmp_path), tmp_path / "log.json"
    _run(path, log)
    data = json.loads(path.read_text())
    assert data["reviewed"] is True
    assert data["strikes_per_category"]["categories"]["hospice"] == 1


def test_every_change_is_logged_with_its_reason(tmp_path):
    path, log = _fixture(tmp_path), tmp_path / "log.json"
    _run(path, log)
    entries = json.loads(log.read_text())
    actions = {c["action"] for c in entries[0]["changes"]}
    assert actions == {"strike", "relabel"}
    assert any(c.get("reason") == "not asking" for c in entries[0]["changes"])


def test_an_unannotated_set_is_refused_not_reported_clean(tmp_path):
    path = tmp_path / "held.json"
    path.write_text(json.dumps({
        "reviewed": False, "registers": ["colloquial"],
        "categories": {"hospice": [{"text": "a line", "register": "colloquial"}]},
        "negatives": {"hospice": []}}), encoding="utf-8")
    result = _run(path, tmp_path / "log.json")
    assert result.returncode == 3
    assert json.loads(path.read_text())["reviewed"] is False


def test_relabel_into_an_unknown_category_is_refused(tmp_path):
    path = tmp_path / "held.json"
    path.write_text(json.dumps({
        "reviewed": False, "registers": ["colloquial"],
        "categories": {"hospice": [{"text": "x", "register": "colloquial",
                                    "note": "relabel: nonsense"}]},
        "negatives": {"hospice": []}}), encoding="utf-8")
    assert _run(path, tmp_path / "log.json").returncode == 2


def test_the_shipped_set_is_still_unreviewed():
    """Guards against this script being run on the real file before a human has read it."""
    data = json.loads((ROOT / "data" / "paraphrases_heldout_v2.json").read_text(encoding="utf-8"))
    assert data["reviewed"] is False, (
        "paraphrases_heldout_v2.json says reviewed=true; if the review has genuinely "
        "landed, delete this test in the same commit that reports the reviewed figures")
