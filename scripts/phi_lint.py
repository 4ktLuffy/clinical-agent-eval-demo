#!/usr/bin/env python3
"""Fail the build if anything in the tree looks like real PHI, PII, or a phone number.

The data in this repository is synthetic and must stay that way. This script is the
mechanical check on that claim. It skips itself, since its own patterns would match.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "reports", "reports-real", "__pycache__", ".venv", ".pytest_cache", "NOTES"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock"}
SELF = Path(__file__).resolve()

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("us-ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-. ])?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("npi", re.compile(r"\bnpi[:# ]*\d{10}\b", re.IGNORECASE)),
    ("crisis-number", re.compile(r"(?<![\w.-])988(?![\w.-])")),
    # An identifier-shaped token that is not one of ours. Every synthetic MRN in this
    # repository is TEST-nnnn; anything else in that shape did not come from here.
    ("non-test-identifier", re.compile(r"\b(?!TEST-)[A-Z]{2,6}-\d{4,}\b")),
]

# The labels in this repository are synthetic and written by us. Claiming otherwise
# would be the most damaging thing the README could get wrong, so it is linted.
FORBIDDEN_PHRASES = ("gold standard", "ground truth", "clinician-labelled", "clinician-labeled")


def files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == SELF:
            continue
        if set(path.relative_to(ROOT).parts) & SKIP_DIRS or path.suffix in SKIP_SUFFIXES:
            continue
        out.append(path)
    return out


def main() -> int:
    hits: list[str] = []
    for path in files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    hits.append(f"{rel}:{lineno}: {name}: {match.group(0)!r}")
            lowered = line.lower()
            for phrase in FORBIDDEN_PHRASES:
                if phrase in lowered:
                    hits.append(f"{rel}:{lineno}: forbidden-phrase: {phrase!r}")

    if hits:
        print("PHI lint failed:")
        for hit in hits:
            print("  " + hit)
        return 1
    print(f"PHI lint passed: {len(files())} files checked, no matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
