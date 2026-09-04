"""No API key may reach a report, an audit line, or any tracked file.

Runs whether or not a key is set: with a key it scans for that key's prefix, and without
one it still proves the scanner works by planting a synthetic key. A check that silently
passes because there was nothing to find is not a check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY_VARS = ("EVAL_MODEL_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
PREFIX_LEN = 8
SCAN_DIRS = ("reports", "reports-real", "audit")


def _scan_targets() -> list[Path]:
    targets: list[Path] = []
    for name in SCAN_DIRS:
        directory = ROOT / name
        if directory.is_dir():
            targets += [p for p in directory.rglob("*") if p.is_file()]
    return targets


def _contains(needle: str, paths: list[Path]) -> list[Path]:
    hits = []
    for path in paths:
        try:
            if needle in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(path)
        except OSError:
            continue
    return hits


@pytest.mark.parametrize("var", KEY_VARS)
def test_no_live_key_prefix_in_reports_or_audit(var):
    value = os.environ.get(var)
    if not value or len(value) < PREFIX_LEN:
        pytest.skip(f"{var} not set")
    hits = _contains(value[:PREFIX_LEN], _scan_targets())
    assert not hits, f"{var} prefix found in: {[str(p) for p in hits]}"


def test_scanner_actually_detects_a_planted_key(tmp_path):
    """Negative control: without this, the tests above pass by finding nothing."""
    planted = tmp_path / "reports"
    planted.mkdir()
    (planted / "leak.json").write_text('{"key": "sk-or-v1-DEADBEEFdeadbeef"}', encoding="utf-8")
    files = [p for p in planted.rglob("*") if p.is_file()]
    assert _contains("sk-or-v1", files), "the scanner failed to find a key it was given"
    assert not _contains("sk-nothere", files)


def test_no_key_shaped_string_is_tracked_in_git():
    """Belt and braces: nothing key-shaped in any tracked file, key set or not."""
    import re
    import subprocess

    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    pattern = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-or-v1-[A-Za-z0-9]{16,})\b")
    offenders = []
    for name in listing.split("\0"):
        if not name:
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            if "test_no_key_leak" in name:
                continue
            offenders.append(f"{name}: {match.group(0)[:12]}...")
    assert not offenders, offenders
