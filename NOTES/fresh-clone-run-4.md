# Fresh-clone run 4 — 2026-09-07, main at 2127849

Cloned `main` and followed `README.md` literally, top to bottom, with Docker running.

| Step | Result |
|---|---|
| `uv venv --python 3.12 && uv pip install -e ".[dev]"` | ok — Python 3.12.13 |
| `make eval` | ok, mutation table reads `not exercised` on all three semantic rows |
| `make readme-check` | ok, 39 numbers, 0 mismatched |
| `make number-audit` | ok, 710 numbers, 0 undeclared |
| `scripts/verify_quotes.py` | ok, 6 phrases, 3 figures current, 6 superseded absent |
| `scripts/phi_lint.py` | ok, 252 files, 4 named fixtures |
| `make scorecard ADAPTER=python:my_agent:draft` | ok, latency heading names the adapter |
| `make fhir-up && make fixture-load` | ok, HAPI ready in 30s, 214 bundles |
| `make verify FHIR_PROFILE=fixture` | ok, replay gate passed |
| `make demo` | ok, hash chain verified |
| `pytest` | **202 passed, 0 skipped** |
| default stage, no key | resolves to `local` (MiniLM), no warning needed |

**Zero deviations.** The Docker-daemon prerequisite added after run 3 is present and
correct, and it is the only thing run 3 found. Everything the README claims a stranger can
run, a stranger can run.

All defects from earlier runs remain fixed: the install command works as written (run 1),
the Python version is pinned in the command (run 1), the mutation table reads
`not exercised` rather than `NO` (run 1), the latency heading names the adapter that
supplied the drafts (run 1), and the Docker prerequisite is stated (run 3).
