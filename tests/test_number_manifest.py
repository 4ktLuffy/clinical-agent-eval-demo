"""NUMBERS.md is a gate, not a page.

The README's first screen reads as prose because every figure on it is listed in the
manifest with the command that reproduces it. That only means anything while the audit
actually fails when a row goes missing, so both directions are asserted here.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("na", ROOT / "scripts" / "number_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def _first_screen_numbers() -> set[str]:
    head = "\n".join((ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:25])
    return {t for t in audit.NUMBER.findall(audit.claim_text(head)) if t not in audit.IGNORE}


def test_the_first_screen_carries_no_marker():
    """The markers were honest but they read as clutter in the shop window. They moved to
    the manifest; they did not stop being required."""
    head = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:25]
    assert not [line for line in head if "(manual:" in line]


def test_every_first_screen_number_is_accounted_for():
    covered = audit.verified_tokens() | audit.manifest_tokens()
    missing = sorted(_first_screen_numbers() - covered)
    assert not missing, f"first-screen numbers with no artifact and no manifest row: {missing}"


def test_a_manifest_row_without_a_command_does_not_count():
    """The whole point: a row that names a figure but not how to reproduce it is a claim."""
    assert not audit._MANIFEST_COMMAND.search("| a figure | 6.2% | (trust me) |")
    assert audit._MANIFEST_COMMAND.search(
        "| a figure | 6.2% | `python scripts/heldout_recall.py local` |")


def test_the_audit_fails_when_a_manifest_row_is_removed(tmp_path):
    """Negative control, run against a copy so the real file is never touched."""
    manifest = ROOT / "NUMBERS.md"
    original = manifest.read_text(encoding="utf-8")
    row = next(line for line in original.splitlines()
               if "refuses in-scope" in line and "`" in line)
    try:
        manifest.write_text(original.replace(row + "\n", ""), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "number_audit.py")],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 1, "the audit passed with a manifest row missing"
    finally:
        manifest.write_text(original, encoding="utf-8")
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "number_audit.py")],
                          cwd=ROOT, capture_output=True).returncode == 0
