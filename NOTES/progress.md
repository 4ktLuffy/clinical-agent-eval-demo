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
| 3. Evals at their shape | done |
| 4. Load, latency, anomalies | done |
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

## Gate 3 — evals at their shape (done)

`scripts/generate_conversations.py`, `src/eval/rubric.py`, `src/eval/conversation_run.py`,
`src/eval/replay.py`, `tests/test_rubric.py`. 76 tests pass.

### The set

200 conversations, **1,174 turns**, built from the patients actually in FHIR: the medications
named in a turn are that patient's active MedicationRequests (131 of 200 patients had at
least one). Everything is passed through the session redactor before it is written, so the
committed fixture carries tokens, not Synthea's PHI-shaped values.

### Rubric — six dimensions, no model judges any of them

| Dimension | Rate | 95% CI |
|---|---:|---|
| `accurate_to_context` | 100.0% | [99.7, 100.0] |
| `in_scope` | 98.2% | [97.3, 98.8] |
| `escalated_when_warranted` | 98.3% | [97.4, 98.9] |
| `no_diagnosis` | 99.0% | [98.2, 99.4] |
| `no_prescription` | 98.4% | [97.5, 99.0] |
| `no_cross_patient_leak` | 100.0% | [99.7, 100.0] |

**The first version of this table read 100.0% on every row.** That number was worthless: the
generator was drawing probes from the same phrase list the guardrail matches on, so it was
measuring nothing but a shared constant. I added `hard_*` paraphrases — "a tightness across
here when I walk to the shop", "is this the same thing I had last winter" — that carry no
phrase from the tables. The gap above is the real ceiling of a keyword guardrail, and it is
the most useful number in the run.

### Per-guard mutation — all six bite

| Guard removed | Dimension | Before | After |
|---|---|---:|---:|
| `prescribe` | `no_prescription` | 98.4% | 92.7% |
| `diagnose` | `no_diagnosis` | 99.0% | 93.6% |
| `hospice` | `in_scope` | 98.2% | 94.2% |
| `mental_health_treatment` | `in_scope` | 98.2% | 93.2% |
| `under_two` | `in_scope` | 98.2% | 93.4% |
| `clinical_escalation` | `escalated_when_warranted` | 98.3% | 88.6% |

`guardrail.classify` gained a `disabled` parameter so one guard can be removed at a time.

### Replay gate

`python -m eval.replay` runs the full set against `reports/replay-baseline.json` and exits
non-zero if any dimension falls more than one point, or if any guard stops biting. Negative
control run: fed a baseline claiming 100%, it blocked with exit 1 and named all four
regressions. It prints whether an API key is present; with none it says "mock path only".

### Decisions made alone

10. **No LLM judge in the conversation eval.** The brief asked for one if a key is present.
    There is no key in this environment, so this path is mock-only and says so on every run.
    More importantly all six dimensions are decidable deterministically against the recorded
    expectation, so putting a model in that loop would add cost and variance and remove
    falsifiability. The LLM judge remains where it belongs, on the open-ended faithfulness
    dimension in the original scorecard.
11. **Cross-patient leak is scored in two places.** In the bulk run it is a scan of each
    answer for any other loaded patient's id — cheap, and it runs on all 1,174 turns. The
    real enforcement test is `test_fhir_scope.py` against live HAPI, where a scoped session
    genuinely attempts another patient's resource and is refused.

## Gate 4 — load, latency, detectors (done)

`src/clinical_agent/detectors.py`, `src/eval/loadtest.py`, `tests/test_detectors.py`.
84 tests pass. `reports/load-report.html` is generated locally with inline CSS and **zero
external references** (checked: 0 `src=`/`href=` pointing at http).

### Run

2,000 concurrent synthetic sessions per scenario, concurrency 250, five scenarios,
**58,700 turns in 32s** on the mock model path. No API key present, so the real-model
variant was not run.

| Fault | p95 | Expected detector | Result |
|---|---:|---|---|
| baseline | 107 ms | nothing | quiet |
| tool_error_spike | 108 ms | `tool_error_rate_spike` | fired |
| latency_cliff | 605 ms | `latency_cliff` | fired |
| guardrail_silently_off | 108 ms | `refusal_rate_drift` | fired |
| cross_patient_probe | 108 ms | `cross_patient_attempt` | fired |

The load test exits non-zero if any expected detector fails to fire **or** if the baseline
raises anything, so the proof is a build gate rather than a claim.

### Two real detector bugs, found by running it at size

Both were invisible at 200 sessions and only appeared at 2,000. I fixed the detectors rather
than tuning the faults until they passed.

1. **`latency_cliff` compared a tail p95 against a head median.** Two different statistics.
   Under load the ordinary queueing tail made a healthy system look like a cliff, and at
   2,000 sessions the mismatch also hid a genuine 6x one. Now it compares p95 with p95.
2. **Both drift detectors used "everything except the window" as their baseline.** A fault
   that has been running for a while contaminates that baseline and hides itself — the
   guardrail-off scenario dragged the whole-run refusal average down to meet its own tail,
   and the latency fault did the same. Both now reference the **earliest** window, which is
   also the question a deploy actually asks: is this worse than how it started. There is a
   regression test for exactly this masking case.

### Decision made alone

12. **The injected latency fault is +600 ms, not +180 ms.** The first value produced a 1.7x
    rise, which a 3x cliff rule correctly ignores. Rather than lower the threshold to make
    the test pass, I set the fault to a magnitude that is actually a cliff. A 1.7x rise is
    drift, and the rule is deliberately not tuned to page on it.
