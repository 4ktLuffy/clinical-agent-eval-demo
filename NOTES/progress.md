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
| 1. Real FHIR (HAPI + Postgres + Synthea) | done |
| 2. MCP server against real FHIR | not started |
| 3. Evals at their shape | not started |
| 4. Load, latency, anomalies | not started |
| 5. Go-live runbook | not started |
| 6. README rewrite | not started |

## Gate 1 — real FHIR (done)

`make fhir-up` brings up HAPI FHIR JPA + Postgres; `make synthea` generates bundles;
`make load` posts them; `make fhir-check` asserts the dataset. All four run clean.

### Versions

| Component | Version |
|---|---|
| HAPI FHIR JPA server | 8.12.0, FHIR R4 4.0.1 (`hapiproject/hapi:latest`) |
| Postgres | 16-alpine |
| Synthea | `master-branch-latest` jar, 188 MB, seed 20260902 |
| Docker server | 29.5.2, arm64 |
| Java | none on the host; Synthea runs in `eclipse-temurin:21-jre` |

### Timings

- Synthea generation, 200 requested: **2m11s**, produced 213 patients (200 alive, 13 dead)
  across 215 bundles, 879 MB of JSON.
- Load into HAPI: **328.1s** for 215 transaction bundles, 0 failed.
- HAPI cold start to first `/metadata` 200: ~90s.

### `make fhir-check` result

```
server: HAPI FHIR Server 8.12.0 FHIR 4.0.1
  ok  Patient                  213  (need >= 150)
  ok  Encounter              11947  (need >= 500)
  ok  MedicationRequest      10337  (need >= 100)
  ok  Condition               8457  (need >= 200)
  ok  Observation           121010  (need >= 500)
```

### Decisions made alone

1. **Separate colima profile.** The default colima VM is `x86_64` and had your containers
   running on it (searxng among them). The amd64 HAPI image crashed under emulation with
   `SIGILL` in JIT-compiled code. Rather than restart your default profile with a different
   architecture — which would have killed those containers — I created a second profile,
   `colima start --profile fhir --arch aarch64`, and the arm64 image runs clean. Your default
   profile was not stopped or reconfigured. Note the active docker context is now
   `colima-fhir`; `docker context use colima` puts it back.
2. **Installed `docker-compose` via Homebrew.** The compose plugin was absent, so
   `docker compose` did not exist. This is a host change I made without asking.
3. **No container healthcheck on the HAPI service.** The image is distroless — no shell, no
   curl — so an in-container healthcheck cannot run and reports `unhealthy` forever. Readiness
   is asserted from the host in `make fhir-up`, which is where a deployment checks it anyway.
4. **Synthea runs in a container, not on the host.** There is no JRE on this machine and I did
   not want to install a JDK system-wide. `make synthea` mounts the jar into
   `eclipse-temurin:21-jre`.
5. **`data/synthea/` and `tools/*.jar` are gitignored** — 879 MB of generated JSON and a
   188 MB jar are build inputs, not source. `make synthea-jar` re-fetches the jar.

### Also fixed while here

`mcp` now installs into a real Python 3.12 venv in the project (2.1.1, matching CI). The
earlier "verified on 3.11 only" caveat is closed: the sandbox network works from inside the
project directory, it was failing for an unrelated reason earlier in the session.
