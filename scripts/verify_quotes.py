#!/usr/bin/env python3
"""Assert every phrase the README quotes from the job posting is verbatim.

The posting text is pinned here rather than fetched, so the check is deterministic and
offline. If the posting changes, this file is what gets updated, deliberately.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

POSTING = (
    "By day 90, you will have completed end-to-end ownership of your first AI deployment: "
    "designed and implemented a RAG pipeline grounded in customer data, built tool-calling "
    "and MCP integrations connecting our agents to customer systems (EHRs, data warehouses, "
    "operational tools), executed a production go-live with zero surprises, and established "
    "monitoring that catches anomalies before customers do. "
    "Build tool-calling and Model Context Protocol (MCP) architectures that enable AI agents "
    "to interact securely with customer systems-EHRs (Epic, Cerner, Athena), data warehouses, "
    "and operational tools-handling errors gracefully and enforcing safety constraints. "
    "Monitor and own production systems by instrumenting deployed agents, responding quickly "
    "to incidents, troubleshooting issues collaboratively with customers."
)

QUOTES = [
    "RAG pipeline grounded in customer data",
    "built tool-calling and MCP integrations",
    "executed a production go-live with zero surprises",
    "established monitoring that catches anomalies before customers do",
    "handling errors gracefully and enforcing safety constraints",
    "instrumenting deployed agents",
]


def main() -> int:
    readme = re.sub(r"\s+", " ", (ROOT / "README.md").read_text(encoding="utf-8"))
    failures = []
    for quote in QUOTES:
        if quote not in POSTING:
            failures.append(f"not verbatim in the posting: {quote!r}")
        if quote not in readme:
            failures.append(f"quoted phrase missing from README: {quote!r}")
    if "before customers notice" in readme:
        failures.append("README says 'before customers notice'; the posting says 'do'")
    if failures:
        for failure in failures:
            print("  " + failure, file=sys.stderr)
        return 1
    print(f"quote check passed: {len(QUOTES)} phrases verbatim and present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
