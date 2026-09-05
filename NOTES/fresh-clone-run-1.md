# Fresh-clone run 1 — 2026-09-05, commit 093d0ee

Cloned into a temp dir and followed `README.md` literally, top to bottom, as a stranger.

| Step | Result |
|---|---|
| `uv pip install -e ".[dev]"` | **FAILED** — "No virtual environment found" |
| `make fhir-up` | ok (10s — but reused a container already running from another checkout) |
| `make fixture-load` | ok, 214 created |
| `make verify FHIR_PROFILE=fixture` | ok, replay gate passed |
| `make eval` | ok |
| `make demo` | ok, hash chain verified across 5 entries |
| `make readme-check` | ok, 39 numbers, 0 mismatched |
| `make scorecard` | ok |
| `make scorecard ADAPTER=python:my_agent:draft` | ok |
| `make scorecard POLICY=/tmp/mypolicy.yaml` | ok |

## Deviations

1. **The install command in the README does not work.** `uv pip install -e ".[dev]"` on a
   fresh clone exits with "No virtual environment found; run `uv venv` ... or pass
   `--system`". The README never says to create a venv. This is the first command a
   stranger runs. **Doc fix.**
2. **"Python 3.12" is stated but not pinned.** `uv venv` gave 3.14.7. Everything passed on
   3.14, so the statement is not wrong so much as unenforced; the README now shows
   `--python 3.12` and says 3.14 also works. **Doc fix.**
3. **The rendered mutation table shows three `semantic ... NO` rows** with no indication
   they are *not exercised*. A reader sees three broken guards. The JSON has carried an
   `exercised` flag since the stage was added; `render()` never printed it. **Code fix.**
4. **The latency heading says "harness only, scripted drafts" even when an adapter or a
   real model supplied the drafts.** Anyone pointing this at their own agent reads a
   latency number labelled as though it came from a script. **Code fix.**
5. Not a defect, checked and dismissed: a `python:module:function` adapter resolves from the
   repository root as well as from `src/`, because Python puts the working directory on
   `sys.path`. The README's wording is accurate.
6. Could not test cleanly: `make fhir-up` reused the HAPI container already running from
   another checkout, so the cold-start path was not exercised in this run.
