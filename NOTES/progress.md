# Overnight build — feat/real-fhir-deployment

Branch: `feat/real-fhir-deployment`. `main` untouched. No PRs, issues, comments or messages.

## Gate 0 — label provenance correction (done)

Corrected a false claim I had introduced. The README, the scorecard renderer and a code
comment all said the judge calibration labels were assigned by "a person". They were not.
I assigned them. They are now described as **reference labels assigned by an AI reader, not
a clinician and not the author**.

**Decision made alone.** The brief asked for the wording "a second AI reader". I did not use
"second", because it is not true and would replace one false provenance claim with another:
there was no independent second reader. The same model that wrote the scripted drafts and
designed the rule judge also assigned these labels. The repo now says exactly that, and marks
the calibration figure provisional, because self-consistency cannot catch a consistent error.
If you want the literal "second AI reader" wording, it needs an actual second pass by a
different model first — say so and I will run one.

Added `NOTES/labeling-sheet.csv` (11 open-ended turns, patient turn, agent answer, cited chunk
ids, full retrieved chunk text, blank faithfulness and citation columns) plus
`NOTES/labeling-sheet-README.md` with the rubric. The provisional AI labels are in the last
two columns so they can be compared after a human pass, or covered to avoid anchoring.

## Environment probe (blocking findings, recorded before starting gate 1)

- No outbound network from this sandbox. `pip` fails with DNS errors; `curl` exits 56.
- `docker` CLI present, **daemon not running**.
- `java` is the macOS stub only: "Unable to locate a Java Runtime". Synthea needs a JRE.
- Local Python is 3.11 via an existing venv, read-only, because `mcp` cannot be installed here.

Consequences for gate 1 are worked in the gate 1 section below.

## Gates

| Gate | Status |
|---|---|
| 0. Label provenance + labeling sheet | done |
| 1. Real FHIR (HAPI + Postgres + Synthea) | in progress |
| 2. MCP server against real FHIR | not started |
| 3. Evals at their shape | not started |
| 4. Load, latency, anomalies | not started |
| 5. Go-live runbook | not started |
| 6. README rewrite | not started |
