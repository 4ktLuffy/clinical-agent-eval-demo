# Fresh-clone run 2 — 2026-09-05, main at 1ee7e0c

Cloned `main` (no branch argument, as a stranger would) and followed `README.md` literally.

| Step | Result |
|---|---|
| `uv venv --python 3.12 && uv pip install -e ".[dev]"` | ok — Python 3.12.13 |
| `make eval` | ok |
| `make readme-check` | ok, 39 numbers, 0 mismatched |
| `make number-audit` | ok, 0 undeclared |
| `make fhir-up && make fixture-load` | ok |
| `make verify FHIR_PROFILE=fixture` | ok, replay gate passed |
| `make demo` | ok, hash chain verified |
| `make scorecard ADAPTER=python:my_agent:draft` | ok |

**Zero deviations.** All four defects from run 1 are fixed and visibly so:

1. The install command works as written; the venv step is there and the Python version is
   pinned in the command rather than only asserted in prose.
2. `uv venv --python 3.12` gives 3.12.13.
3. The mutation table reads `not exercised` where it used to read `NO`.
4. The latency heading reads "end to end, drafts from `python:my_agent:draft`" when an
   adapter supplied the drafts, instead of "harness only, scripted drafts".

The one thing run 1 could not test — a cold FHIR start, because a container from another
checkout was already up — was exercised here from a clean clone and worked.
