"""Every number in the docs is either diffed against an artifact or declared manual.

`make readme-check` regenerates a set of numbers from committed artifacts and diffs them.
That leaves the rest — held-out per-category rows, sweep latencies, hand-read verdicts —
true but unchecked, and a reader cannot tell which kind they are looking at.

This audits the gap. A number passes if either:

  * it appears in a value readme_check regenerated from an artifact, or
  * it sits in a block carrying a `(manual: <command>)` marker naming what reproduces it.

Anything else fails the build. The marker is deliberately visible in the rendered document:
a reader should be able to see which numbers are machine-checked and which are a claim with
a recipe attached.

Blocks are markdown paragraphs and tables. A marker applies to its own block, and a marker
on a heading applies until the next heading of the same or higher level.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "FINDINGS.md", "LIMITATIONS.md")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")
MARKER = re.compile(r"\(manual: *([^)]+)\)")
HEADING = re.compile(r"^(#+)\s")

# Numbers that carry no claim on their own.
IGNORE = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}

# Stripped before extraction, because none of these is a measurement: inline code (model
# names like `gpt-oss-120b`, thresholds quoted as identifiers, commit shas), link targets
# and bare URLs (issue numbers, posting ids), and image paths.
_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_IMG = re.compile(r"!\[[^\]]*\]")


def claim_text(body: str) -> str:
    for pattern in (_CODE, _LINK, _URL, _IMG):
        body = pattern.sub(" ", body)
    return body


def verified_tokens() -> set[str]:
    spec = importlib.util.spec_from_file_location("rc", ROOT / "scripts" / "readme_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks, _ = module.build_checks()
    tokens: set[str] = set()
    for check in checks:
        tokens.update(NUMBER.findall(check.expected))
    # A percentage is diffed as "98.3%"; the same value appears bare in prose.
    tokens.update({t.rstrip("%") for t in list(tokens)})
    return tokens


def blocks(text: str):
    """Yield (line number, block text, marker in force).

    A marker on a heading applies until the next heading at the same or a higher level; a
    marker inside a block applies to that block only. Tracked as an explicit stack keyed by
    level, rebuilt at every heading, because the first version kept stale deeper entries and
    handed a trailing paragraph a marker from a section it was not in -- which made the gate
    unable to fail its own negative control.
    """
    lines = text.splitlines()
    stack: list[tuple[int, str]] = []          # (heading level, marker)
    current: list[str] = []
    start = 1

    def in_force() -> str | None:
        return stack[-1][1] if stack else None

    def flush(at: int):
        if not current:
            return None
        body = "\n".join(current)
        own = MARKER.search(body)
        return at, body, (own.group(1) if own else in_force())

    for index, line in enumerate(lines, 1):
        heading = HEADING.match(line)
        if heading:
            pending = flush(start)
            if pending:
                yield pending
            current = []
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            found = MARKER.search(line)
            if found:
                stack.append((level, found.group(1)))
            continue
        if line.strip():
            if not current:
                start = index
            current.append(line)
            continue
        pending = flush(start)
        if pending:
            yield pending
        current = []

    pending = flush(start)
    if pending:
        yield pending


def main() -> int:
    verified = verified_tokens()
    undeclared: list[str] = []
    declared = auto = 0
    for name in DOCS:
        path = ROOT / name
        if not path.exists():
            continue
        for line_no, body, marker in blocks(path.read_text(encoding="utf-8")):
            tokens = [t for t in NUMBER.findall(claim_text(body)) if t not in IGNORE]
            if not tokens:
                continue
            # Counted first, so a heading marker does not disguise how many numbers are
            # actually machine-checked. A marked block still reports its diffed share.
            missing = [t for t in tokens if t not in verified]
            auto += len(tokens) - len(missing)
            if marker:
                declared += len(missing)
                continue
            if missing:
                undeclared.append(
                    f"{name}:{line_no}: {sorted(set(missing))[:6]}"
                    f"{' ...' if len(set(missing)) > 6 else ''}")
    total = auto + declared
    share = (auto / total * 100) if total else 0.0
    print(f"number audit: {auto} of {total} numbers auto-diffed ({share:.0f}%), "
          f"{declared} declared manual with a command, "
          f"{len(undeclared)} undeclared")
    for row in undeclared:
        print(f"  {row}")
    if undeclared:
        print("\nEvery number must be regenerated by readme-check or sit in a block marked "
              "(manual: <command>).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
