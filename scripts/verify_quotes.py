#!/usr/bin/env python3
"""Assert the README describes the artefact and nothing else.

This file used to do the opposite. It checked that six phrases from a job posting and three
company figures were quoted verbatim in the README, because the repository was framed as an
application. That framing has been removed: the README is now about the software.

The check is kept and inverted rather than deleted. A gate that no longer has a subject
should not quietly become a no-op, and the failure mode it now guards is real — application
framing, an employer's figures, or the author's CV drifting back into a technical README.

What may still appear, and why:
  * the disclaimer that this is not any vendor's system, which protects a reader from
    mistaking a demo for a product;
  * source citations inside the code and the labelling rules, which say where the scope
    categories came from. Those are provenance for the artefact, not a pitch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Phrases that only make sense if the README is an application. None may appear.
APPLICATION_FRAMING = (
    "forward deployed engineer",
    "jobs.ashbyhq.com",
    "day-90",
    "day 90",
    "by day 90",
    "a miniature of that arc",
    "related work",
    "hiring",
    "my cv",
    "cover note",
)

# Company figures. Fine in a recon note; not in a README about the software.
COMPANY_FIGURES = ("$444M", "$404M", "250M+", "300+ live use cases", "$126M")

# The disclaimer must stay: removing it is how a demo gets mistaken for a product.
REQUIRED = ("This is not a Hippocratic AI system.",)


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", readme).lower()
    failures: list[str] = []

    for phrase in APPLICATION_FRAMING:
        if phrase in flat:
            failures.append(f"application framing back in the README: {phrase!r}")
    for figure in COMPANY_FIGURES:
        if figure.lower() in flat:
            failures.append(f"employer figure back in the README: {figure!r}")
    for phrase in REQUIRED:
        if phrase not in readme:
            failures.append(f"required disclaimer missing: {phrase!r}")

    if failures:
        for failure in failures:
            print("  " + failure, file=sys.stderr)
        print("\nThe README describes the software. Recon, employer figures and anything "
              "about the author belong elsewhere.", file=sys.stderr)
        return 1
    print(f"README check passed: {len(APPLICATION_FRAMING)} framing phrases and "
          f"{len(COMPANY_FIGURES)} employer figures absent, "
          f"{len(REQUIRED)} disclaimer present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
