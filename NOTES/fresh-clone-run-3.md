# Fresh-clone run 3 — 2026-09-07, main at 24342f2

Cloned `main` and followed `README.md` literally, top to bottom.

| Step | Result |
|---|---|
| `uv venv --python 3.12 && uv pip install -e ".[dev]"` | ok — Python 3.12.13 |
| `make eval` | ok, mutation table reads `not exercised` |
| `make readme-check` | ok, 39 numbers, 0 mismatched |
| `make number-audit` | ok, 0 undeclared |
| `scripts/verify_quotes.py` | ok |
| `scripts/phi_lint.py` | ok, 233 files |
| `make scorecard ADAPTER=python:my_agent:draft` | ok, latency heading names the adapter |
| `make fhir-up && make fixture-load` | ok after starting Docker — see the deviation |
| `make verify FHIR_PROFILE=fixture` | ok, replay gate passed |
| `make demo` | ok, hash chain verified across 5 entries |

**One deviation, fixed in the docs.** With no Docker daemon running, `make fhir-up` fails
with docker's own error. That message is clear enough on its own, but the README never said
a daemon was needed: it moved straight from `pip install` to `make fhir-up`. A reader
following it literally on a machine where Docker is not started hits a wall the document
did not warn them about. The Running-it section now says so before the first command that
needs it. No code changed.

Everything else matched the README exactly. The two defects from run 1 that run 2 confirmed
fixed — the mutation table's `not exercised`, and the latency heading naming the adapter
that supplied the drafts — are still correct here.
