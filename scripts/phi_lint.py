#!/usr/bin/env python3
"""Fail the build if anything in the tree looks like real PHI, PII, or a phone number.

The data in this repository is synthetic and must stay that way. This script is the
mechanical check on that claim. It skips itself, since its own patterns would match.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generated report directories are NOT skipped. They are exactly where a redaction failure
# would surface -- drafts.jsonl holds real model output -- and skipping them meant the lint
# had never once looked at the artifacts the repository publishes.
SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache", "node_modules"}
# NOTES/ is tracked and therefore ships, so it IS scanned for PHI patterns. It is exempt
# only from the forbidden-phrase check, because the design note legitimately quotes the
# banned words in the course of stating the rule about them.
PHRASE_EXEMPT_DIRS = {"NOTES"}

# Files that must contain identifier-shaped strings to do their job. Named one by one, not
# by pattern, and printed on every run: an exemption nobody sees is a hole. Every value in
# these is drawn from a reserved range (example.com, Ofcom drama numbers 07700 900xxx, the
# 078-05-1120 specimen SSN) and none of it is real.
IDENTIFIER_FIXTURES = {
    "tests/test_runtime_phi.py",
    # An injection that asks the agent to read out another patient's record has to
    # contain a record-number shape to be the threat it models. If that string ever
    # reaches a report, the lint catches it there -- report directories are not exempt.
    "data/injection/tool_result_injections.json",
    # The redaction module must contain the shapes it redacts, exactly as this linter must
    # contain the shapes it looks for. Both are pattern definitions, not data.
    "src/clinical_agent/phi.py",
}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock"}
SELF = Path(__file__).resolve()

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("us-ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-. ])?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    # The lint scanned only US shapes until a planted UK number walked straight through a
    # generated report. A pattern set that cannot fail its own negative control is decoration.
    ("uk-phone", re.compile(r"\b0\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b")),
    ("uk-dob", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")),
    ("mrn", re.compile(r"\b(?:MRN|NHS(?:\s+number)?|record\s+number)\b"
                       r"(?:\s+(?:is|no\.?|number|#))?[:\s#]*[A-Z]{0,3}\d[\d\s-]{4,}\d",
                       re.IGNORECASE)),
    ("npi", re.compile(r"\bnpi[:# ]*\d{10}\b", re.IGNORECASE)),
    ("crisis-number", re.compile(r"(?<![\w.-])988(?![\w.-])")),
    # An identifier-shaped token that is not one of ours. Every synthetic MRN in this
    # repository is TEST-nnnn; anything else in that shape did not come from here.
    ("non-test-identifier", re.compile(r"\b(?!TEST-)[A-Z]{2,6}-\d{4,}\b")),
]

# The labels in this repository are synthetic and written by us. Claiming otherwise
# would be the most damaging thing the README could get wrong, so it is linted.
FORBIDDEN_PHRASES = ("gold standard", "ground truth", "clinician-labelled", "clinician-labeled")

# A line carrying this marker is exempt. It exists for one case only: the redaction tests,
# which must contain PHI-shaped literals in order to prove they get removed. It is a
# per-line pragma rather than a per-file exemption so that every use is visible in a diff.
PRAGMA = "phi-lint: allow-fixture"


def files() -> list[Path]:
    """Everything that could reach the repository: tracked files plus untracked ones that
    are not gitignored. Ignored paths are excluded deliberately -- generated Synthea
    bundles are hundreds of megabytes of PHI-shaped synthetic values that never ship.
    Falls back to a plain walk outside a git checkout."""
    candidates: list[Path]
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, capture_output=True, check=True, text=True,
        ).stdout
        candidates = [ROOT / name for name in listing.split("\0") if name]
        # git ls-files misses untracked report directories; a freshly generated report is
        # precisely the thing worth linting before it is committed.
        for directory in sorted(ROOT.glob("reports*")):
            candidates += [p for p in directory.rglob("*") if p.is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        candidates = list(ROOT.rglob("*"))

    out = []
    for path in candidates:
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
        if str(rel) in IDENTIFIER_FIXTURES:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if PRAGMA in line:
                continue
            for name, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    hits.append(f"{rel}:{lineno}: {name}: {match.group(0)!r}")
            if set(rel.parts) & PHRASE_EXEMPT_DIRS:
                continue
            lowered = line.lower()
            for phrase in FORBIDDEN_PHRASES:
                if phrase in lowered:
                    hits.append(f"{rel}:{lineno}: forbidden-phrase: {phrase!r}")

    if hits:
        print("PHI lint failed:")
        for hit in hits:
            print("  " + hit)
        return 1
    print(f"PHI lint passed: {len(files())} files checked, no matches "
          f"(fixtures exempted: {sorted(IDENTIFIER_FIXTURES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
