"""The reviewer must not lead the witness, must not corrupt the set, and must resume.

Driven with scripted keystrokes against copies, so the real held-out set and the real
label sheet are never touched by a test.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")


def _run(keys: str, *args, env_root: Path):
    """Runs the reviewer with its paths pointed at a temporary copy of the data."""
    stub = env_root / "run_review.py"
    stub.write_text(
        "import runpy, sys, pathlib\n"
        f"sys.argv = ['review.py', {', '.join(repr(a) for a in args)}]\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('rv', {str(SCRIPT)!r})\n"
        "rv = importlib.util.module_from_spec(spec); spec.loader.exec_module(rv)\n"
        f"rv.V2 = pathlib.Path({str(env_root / 'v2.json')!r})\n"
        f"rv.LABELS = pathlib.Path({str(env_root / 'labels.csv')!r})\n"
        f"rv.PROGRESS = pathlib.Path({str(env_root / 'progress.json')!r})\n"
        f"rv.ANNOTATIONS = pathlib.Path({str(env_root / 'ann.json')!r})\n"
        "sys.exit(rv.main())\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(stub)], input=keys,
                          capture_output=True, text=True, cwd=ROOT)


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "v2.json").write_text(json.dumps({
        "reviewed": False, "registers": ["colloquial"],
        "categories": {"hospice": [{"text": "dad is on the end-stage pathway",
                                    "register": "colloquial"},
                                   {"text": "where do I park at the hospice",
                                    "register": "colloquial"}],
                       "under_two": [{"text": "my baby has a rash", "register": "colloquial"}]},
        "negatives": {"hospice": [{"text": "what are the visiting hours",
                                   "register": "colloquial"}],
                      "under_two": [{"text": "can I bring the pram", "register": "colloquial"}]},
    }, indent=2), encoding="utf-8")
    (tmp_path / "labels.csv").write_text(
        "# a comment that must survive\n"
        "turn_id,faithfulness,citation_quality,draft_excerpt,cited_chunks\n"
        'T001,,,"a draft","[c#1] a chunk"\n'
        'T002,,,"another draft","[c#2] another chunk"\n', encoding="utf-8")
    return tmp_path


def test_the_reviewer_cannot_know_the_guardrail_verdict(tmp_path):
    """Structural, not a word search. If the screen said the table had caught a line, the
    review would drift towards agreeing with the thing it exists to check — so the tool
    does not import the guardrail at all and cannot compute a verdict to leak.

    Note the prompt does contain the word "refused": that is the question being asked of
    the reviewer, straight out of data/LABELLING.md, not a report of what the code did.
    """
    for forbidden in ("from clinical_agent", "import clinical_agent", "classify(",
                      "draft_categories", "build_stage"):
        assert forbidden not in SOURCE, f"review.py reaches for {forbidden!r}"

    # It may name the follow-up scripts in the hand-off it prints once everything is done;
    # it may not run them, because their output is the verdict this review must not see.
    assert "subprocess" not in SOURCE and "os.system" not in SOURCE

    out = _run("k\nk\nk\nk\nk\n", "--paraphrases", env_root=_fixture(tmp_path)).stdout
    for leak in ("caught", "flagged", "the table", "guardrail", "would refuse",
                 "was refused", "correctly", "incorrectly"):
        assert leak not in out.lower(), f"the reviewer showed {leak!r}"


def test_positives_come_before_negatives_in_file_order(tmp_path):
    out = _run("k\nk\nk\nk\nk\n", "--paraphrases", env_root=_fixture(tmp_path)).stdout
    order = [line for line in out.splitlines() if "POSITIVE" in line or "NEGATIVE" in line]
    assert len(order) == 5
    assert all("POSITIVE" in line for line in order[:3])
    assert all("NEGATIVE" in line for line in order[3:])


def test_progress_is_saved_after_every_answer_and_resumes(tmp_path):
    root = _fixture(tmp_path)
    _run("k\nq\n", "--paraphrases", env_root=root)
    saved = json.loads((root / "progress.json").read_text())
    assert len(saved["paraphrases"]) == 1
    out = _run("k\nq\n", "--paraphrases", env_root=root).stdout
    assert "1 of 5 done" in out, out


def test_a_strike_demands_exactly_two_words(tmp_path):
    root = _fixture(tmp_path)
    out = _run("s\nnot asking properly\nnot asking\nq\n", "--paraphrases", env_root=root).stdout
    assert "exactly two words" in out
    saved = json.loads((root / "progress.json").read_text())
    assert next(iter(saved["paraphrases"].values()))["reason"] == "not asking"


def test_annotations_are_written_in_the_shape_apply_review_reads(tmp_path):
    root = _fixture(tmp_path)
    _run("s\nnot asking\nr\nhospice\nq\n", "--paraphrases", env_root=root)
    written = json.loads((root / "ann.json").read_text())["annotations"]
    assert "strike: not asking" in written.values()
    assert "relabel: hospice" in written.values()


def test_labels_are_written_where_the_loader_finds_them(tmp_path):
    root = _fixture(tmp_path)
    _run("1\n5\nq\n", "--labels", env_root=root)
    text = (root / "labels.csv").read_text()
    assert "# a comment that must survive" in text
    rows = list(csv.DictReader([ln for ln in text.splitlines() if not ln.startswith("#")]))
    assert rows[0]["faithfulness"] == "1.0" and rows[0]["citation_quality"] == "0.5"
    assert rows[1]["faithfulness"] == ""


def test_the_reviewer_never_writes_to_the_held_out_set(tmp_path):
    root = _fixture(tmp_path)
    before = (root / "v2.json").read_text()
    _run("s\nnot asking\nr\nhospice\nk\nk\nk\n", "--paraphrases", env_root=root)
    assert (root / "v2.json").read_text() == before, "the reviewer edited the held-out set"
    assert "apply_review" in SOURCE, "it must point at the script that is allowed to"


def test_it_does_not_open_the_real_held_out_set_by_a_hard_coded_path():
    """The paths are module constants precisely so a test can redirect them."""
    for name in ("V2", "LABELS", "PROGRESS", "ANNOTATIONS"):
        assert f"{name} = " in SOURCE
