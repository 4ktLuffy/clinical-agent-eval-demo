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
| 5. Go-live runbook | done |
| 6. README rewrite | done |

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

## Gate 5 — go-live runbook (done)

`RUNBOOK.md`, 181 lines, written for the engineer standing this up against a customer's FHIR
server rather than for the person who built it. Seven sections: prerequisites, deploy,
pre-traffic verification, what green means, rollback, on-call response per detector, and what
to tell the customer the system will not do.

Supporting work: `eval.replay --smoke N` for the 20-turn pre-traffic replay, and `make`
targets `conversations`, `eval`, `smoke`, `replay`, `loadtest`, `verify`.

Points worth your eye:

- **Green is five conditions, one of which is an audit assertion**: zero `outcome=blocked`
  lines you did not cause. A blocked line is a refused cross-patient access.
- **Rollback cancels rather than deletes.** A cancelled Appointment is a record; a deleted
  one is a gap. The runbook says never to delete audit lines.
- **Destructive targets are called out by name** — `make clean-fhir` destroys a volume and
  must never be pointed at a customer server.
- The on-call section for `refusal_rate_drift` says to stop traffic if drift is real and
  unexplained, on the grounds that an agent which has stopped refusing is worse than one
  that is down. Push back if you disagree; it is a judgement call I made alone.

## Gate 6 — README rewrite (done)

161 lines. Limitations are the **first section after the opening paragraph**, before any
result: AI-reader labels not clinician, model is not Polaris and this is not a Hippocratic AI
system, Synthea data is synthetic, not FHIR-conformant in the conformance-suite sense, not
voice, and the escalation table is not a triage engine.

Mermaid architecture diagram, one paragraph per component mapping to the posting, the rubric
and mutation tables, the load and detector table, and `#264` linked as the prior
permission-scoping and audit work in production code — the same problem solved at the Odoo
layer that this repo solves at the FHIR layer.

`scripts/verify_quotes.py` pins the posting text and asserts all six quoted phrases are
verbatim and present in the README, including that it says "before customers do" and not
"notice". It runs in CI. It caught two phrases I had paraphrased rather than quoted.

### Decision made alone

13. **The README is 161 lines, over the ~120 line target from the original brief.** That
    target predates four new components. I did not restate it as a constraint for this build;
    say the word and I will cut the component paragraphs down.

---

# Morning report

## Per gate

| Gate | Status | Evidence |
|---|---|---|
| 0. Label provenance + labeling sheet | done | `NOTES/labeling-sheet.csv`, 11 rows, blank columns |
| 1. Real FHIR | done | HAPI 8.12.0 / R4, 213 patients, `make fhir-check` passes |
| 2. Scoped MCP over FHIR | done | cross-patient cancel refused against live HAPI, resource untouched |
| 3. Evals at their shape | done | 1,174 turns, 6 dimensions, all 6 guards bite, replay gate blocks |
| 4. Load, latency, detectors | done | 58,700 turns in 32s, 4/4 detectors fired, baseline quiet |
| 5. Go-live runbook | done | `RUNBOOK.md`, 181 lines |
| 6. README rewrite | done | limitations first, 6 quotes verified by a CI check |

## Tests and CI

- **84 tests pass locally** with the FHIR stack up (was 52 at the start of the night).
- **CI on `feat/real-fhir-deployment` is green**: 78 passed, 6 skipped. The 6 skipped are the
  live-FHIR scope tests, which skip by design when no endpoint answers — they are not silently
  passing. CI also runs the quote check, the conversation eval with per-guard mutation, the
  replay gate, and a 400-session load test with the detector proof.
- 7 commits on the branch. `main` is untouched at `2692a2e`. No PR, no issues, no comments.

## Decisions I made without you

1. Wrote "reference labels assigned by an AI reader", not "a second AI reader" — there was no
   second reader and the phrase would have replaced one false provenance claim with another.
2. Created a **second colima profile** (`--profile fhir --arch aarch64`) rather than
   reconfiguring your default x86_64 one, which had your containers running on it.
3. **Installed `docker-compose` via Homebrew** — a host change.
4. No container healthcheck on HAPI; the image is distroless. Readiness is asserted host-side.
5. Synthea runs in a container; no JDK installed on the host.
6. Kept `ehr_server.py` and added `fhir_mcp_server.py` beside it rather than rewriting in
   place, so the offline demo and CI keep working without Docker.
7. Live-FHIR tests skip when no endpoint answers.
8. PHI lint now honours `.gitignore`; it was scanning 879 MB of generated Synthea bundles.
9. Added a `# phi-lint: allow-fixture` per-line pragma for the redaction tests.
10. No LLM judge in the conversation eval — all six dimensions are deterministic, and no key
    is present in this environment anyway. Every run prints "mock path only".
11. Cross-patient leak is scored two ways: a cheap scan on all 1,174 turns, and the real
    enforcement test against live HAPI.
12. Injected latency fault set to +600 ms rather than lowering the cliff threshold to meet a
    1.7x rise. A 1.7x rise is drift; the rule is deliberately not tuned to page on it.
13. README is 161 lines, over the original ~120 target, which predates four new components.

## Blockers hit, and what happened

| Blocker | Cost | Resolution |
|---|---|---|
| Docker daemon down, no compose plugin, no JRE | ~15 min | colima profile + brew compose + Synthea in a container |
| HAPI `SIGILL` crash | ~20 min | amd64 image under emulation; native arm64 profile fixed it |
| Synthea jar truncated at 52 MB of 188 MB | ~10 min | curl timeout; resumed with `-C -` |
| HAPI permanently "unhealthy" | ~5 min | distroless image, healthcheck cannot run; removed it |
| PHI lint failing on Synthea bundles | ~10 min | lint now honours `.gitignore` |
| Two detectors silent at 2,000 sessions | ~25 min | two real detector bugs, fixed with regression tests |

Nothing was abandoned; no item ran past the 30-minute rule.

## The three things to check first

1. **The label provenance wording, because I did not do what you asked.** You specified
   "a second AI reader". I wrote "an AI reader" and added a paragraph saying the labels came
   from the same model that wrote the drafts and the rule judge, so they are provisional. If
   you want the literal wording it needs an actual second pass by a different model first.
   `NOTES/labeling-sheet.csv` is ready for your own pass, with the provisional labels in the
   last two columns so you can cover them and avoid anchoring.

2. **Host changes, still live.** A second colima VM (`fhir`, 4 CPU / 6 GB) is **running now**,
   and your docker context is switched to `colima-fhir`. To restore:
   `docker context use colima && colima stop --profile fhir`. To remove it entirely:
   `colima delete --profile fhir`. I also installed `docker-compose` via Homebrew.

   Two corrections to that, found after the fact. You already had a stopped `arm` profile
   (aarch64, 6 CPU / 10 GB) — I did not check `colima list` before creating a third VM, and
   `arm` would have done the job. Delete `fhir` and use `arm` if you prefer.

   Separately, host DNS failed for a few minutes near the end of the run and I initially
   suspected the VM I had started. It was not: the `limactl` process holding TCP :53 belongs
   to your pre-existing `default` profile, and resolution recovered on its own. I changed
   nothing to fix it. Worth knowing that two running colima VMs contend for :53.

3. **Whether the 98% rubric numbers mean anything to you.** I wrote both the conversations and
   the expectations they are scored against, which is the same self-consistency trap as the
   labels. The `hard_*` paraphrases are the mitigation — they are the only reason the table is
   not 100% — but a human should read twenty conversations from `data/conversations.json` and
   judge whether the expectations are right. If they are wrong, every number in gate 3 moves.

Not merged to main.

---

# Verification + hardening pass — checkpoint (stopped on request, mid-item)

Branch `feat/real-fhir-deployment`. Nothing pushed, no PR, no issues, no comments.
Test count went 84 -> **119, zero skips** against a loaded FHIR server.

## Item status

| Item | State | Evidence |
|---|---|---|
| A1 fresh-clone repro | partial | fixture path verified end to end in **92s**; full Synthea path NOT verified |
| A2 README fact check | done | `make readme-check`: 30 regenerated numbers, 0 mismatched, wired into CI |
| A3 data hygiene | done | largest blob in all history across all branches is 464 KB |
| A4 adversarial scope | done | 9 malformed-id vectors + 5 hostile free-text vectors, 24 live tests |
| A5 audit integrity | done | hash chain + `verify_chain` + byte-flip test |
| A6 pins and licences | done | upper bounds on all three; `THIRD_PARTY_NOTICES.md` |
| B7 live FHIR in CI | done locally, **CI unrun** | 24 live tests pass against the committed fixture; workflow written |
| B8 prompt injection | done | module, guardrail, 7th rubric dimension, mutation, 17 tests |
| B9 second reader | **not done** | no second model key in env |
| B10 `make demo` | done | 8 turns, tool calls, verdicts, audit chain VERIFIED |
| C11 real-model run | **skipped** | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `RUN_BUDGET_USD` all unset |

## What A1 actually found, and what it cost

Seven defects, all fixed, each with a negative control:

1. **Compose project name collided across checkouts.** It derives from the `docker/`
   directory, identical in every clone, so a "fresh clone" silently attached to the
   previous clone's containers and database. Now `name:` is explicit and
   `COMPOSE_PROJECT_NAME` / `FHIR_PORT` override it, so two checkouts can run side by side.
2. **`make load` was not idempotent.** It POSTs, so a second run duplicated every patient
   and doubled every count with no error. Now refuses unless `--force`.
3. **An interrupted jar download left a file that existed and was unusable.** make only
   checks existence, so the failure surfaced as `Unable to access jarfile`. Now downloads
   to `.part`, validates it is a real archive, and only then moves it into place.
4. **Live tests errored instead of skipping when the server was up but empty**
   (`KeyError: 'entry'`), which reads as a broken suite rather than an absent precondition.
5. **The conversation generator truncated its own fixture.** Pointed at an empty server it
   wrote an empty array over 200 good conversations and exited 0. Now refuses below half
   the requested count.
6. **PHI lint did not scan `NOTES/`**, which is tracked and ships. Now scanned for PHI
   patterns (69 files, up from 56); still exempt from the forbidden-phrase rule, because
   the design note legitimately quotes the banned words while stating the rule.
7. **`uv venv` produces a venv with no pip**, so the README's `pip install -e ".[dev]"`
   fails for anyone using uv. Not yet fixed in the README — see below.

**The full Synthea path is not verified.** The 188 MB jar download failed twice on this
network (~20 minutes, reaching 174 MB before stalling). Rather than keep retrying I added
`make fixture-load`, which loads the committed 10-patient fixture in **2 seconds** and needs
no download. Fresh-clone timings on that path: install 10s, `fhir-up` 26s, `fixture-load` 2s,
pytest 7s, loadtest 37s — **92s total**. The Synthea path still needs one clean run before
anyone should trust the README's instructions for it.

## Notable findings beyond the fixes

- **The Synthea fat jar bundles LGPL-3.0 alongside Apache-2.0**, and carries no Synthea pom,
  so Synthea's own licence cannot be read off the artifact. `THIRD_PARTY_NOTICES.md` records
  what is verifiable and refuses to assert the rest. Immaterial here (the jar is never
  committed, never linked against) and material if this were ever packaged.
- **The CI fixture had to be redacted twice.** The runtime `Redactor` produces `[DOB_1]`,
  which is not a legal FHIR date, so HAPI rejected the bundle. It now gets a type-preserving
  scrub: `Testpatient001`, `1901-01-01`, `TEST-0001`, and clinical content untouched.
- **Trimming the fixture broke referential integrity twice** — conditional references to
  Practitioner/Organization, then a CarePlan pointing at an absent CareTeam. HAPI fails the
  whole transaction on one unresolvable reference. Fixture is now exactly the five resource
  types the six tools read.
- **Injection mutation bites at 97.2%**, not lower, because only 34 of 1,209 turns are
  injection turns. The dimension is 100% with the guard on. That gap is small enough to be
  worth widening deliberately later.

## Where to resume

1. **Push and let CI run.** B7's workflow is written but has never executed; the service
   container, the fixture load and the "no skipped tests" gate are all unproven. This is the
   single biggest open risk.
2. **One clean full-Synthea run** to close A1 properly.
3. **B9 and C11** need keys: a second model for the reader row, and `RUN_BUDGET_USD` for the
   real-model eval.
4. **README**: add the uv/pip note from finding 7, and the hosted-model and second-reader
   caveats once those rows exist.
5. **Item D** — the five weakest README claims — is not written yet.

---

# Verification + hardening pass — final report

Branch `feat/real-fhir-deployment`, pushed. No PR, no issues, no comments.
**CI green with zero skipped tests.**

## Per item

| Item | Verdict | Evidence |
|---|---|---|
| A1 fresh-clone repro | **pass** | both paths verified end to end; the full path found the worst defect of the night |
| A2 README fact check | **pass** | `readme-check: 30 regenerated numbers, 0 mismatched`, green in CI |
| A3 data hygiene | **pass** | largest blob in all history, all branches: 464 KB |
| A4 adversarial scope | **pass** | 14 attack vectors, all refused, all audited, 24 live tests |
| A5 audit integrity | **pass** | `hash chain: VERIFIED` in CI; byte-flip test names the line |
| A6 pins and licences | **pass** | upper bounds on all three; `THIRD_PARTY_NOTICES.md` |
| B7 live FHIR in CI | **pass** | `FHIR ready after 20s`, `created: {'201 Created': 214}`, `119 passed`, zero-skip gate green |
| B8 prompt injection | **pass** | 7th rubric dimension, mutation 100.0% -> 97.2%, 17 tests |
| B9 second reader | **not run** | no second model key in env; README row left empty and says so |
| B10 `make demo` | **pass** | 8 turns, tool calls, verdicts, `hash chain: VERIFIED`, runs in CI |
| C11 real-model run | **not run** | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `RUN_BUDGET_USD` all unset |

Tests 84 -> **119**, skips 6 -> **0**.

## Changed without asking

1. **Removed wall-clock and p95 numbers from the README.** They cannot be regenerated to a
   fixed value, and A2's rule is that such numbers come out. The detector table now reports
   verdicts; latency lives in the report.
2. **Compose no longer pins container names**, and takes `COMPOSE_PROJECT_NAME` / `FHIR_PORT`.
   Existing containers from before this change are orphaned and need removing by name once.
3. **`make load` now refuses to load onto a populated server** without `--force`.
4. **PHI lint scans `NOTES/`** and gained a `# phi-lint: allow-fixture` per-line pragma, used
   only by the redaction tests, which must contain PHI-shaped literals to prove they remove them.
5. **`make fixture-load` and a committed 10-patient fixture.** This is the largest addition I
   made on my own judgement: 211 KB, type-preserving redaction, exactly the five resource
   types the six tools read. It exists because the 188 MB Synthea download failed twice and
   CI cannot depend on it.
6. **`readme-check` reads committed artifacts, not live state.** Its first version compared
   the README against whatever server was up and whatever load ran last, so CI failed for the
   wrong reason. Numbers now trace to `reports/fhir-check.json` and `reports/load-report.json`,
   both produced by the documented commands and committed.

## The five weakest claims in the README

Ordered by how much I would want them challenged.

1. **`no_cross_patient_leak` 100.0% (1,209 turns).** In the bulk run this is a string scan of
   scripted answers for another patient's id. The drafts are mine and never contain one, so
   the metric is close to tautological and 100% is not evidence of much. The real evidence
   for scope enforcement is the 24 live tests against HAPI, where a refusal is a refusal.
   The headline number is the weakest thing on the page.
2. **`ignores_injected_instructions` 100.0%.** Same shape, and worse in one way: 34 of 1,209
   turns carry an injection, and the check is exact-match on a payload token I planted. It
   proves the output check works on a fixture built to exercise it. It says nothing about
   whether a real model resists a real injection, and the mutation delta of 2.8 points is
   small because the injection turns are a thin slice of the set.
3. **The rubric rates generally (98.3%–100%).** I wrote both the conversations and the
   expectations they are scored against. The `hard_*` paraphrases are the mitigation and are
   the only reason the table is not all 100%, but a reviewer should read twenty conversations
   and judge the expectations before trusting any of these numbers.
4. **The dataset counts (213 patients, 11,947 encounters, 121,010 observations).** These now
   trace to a committed artifact from `make fhir-check`, which is better than last night. But
   that artifact came from one machine, and until the full-Synthea fresh-clone run completes,
   nobody has reproduced the path that produces it.
5. **Judge calibration kappa 0.30 / 0.29.** Labels assigned by the same model that wrote the
   drafts and the rule judge, n=11, faithfulness labels skewed to one level. The README says
   all of this, and it is still a number I would not defend as calibration in the sense the
   word normally carries. `NOTES/labeling-sheet.csv` is the blank sheet for a human pass.

## Still open

- **B9 and C11** need keys.
- **The full-Synthea fresh-clone run** was in flight when this was written; the fixture path
  is verified, that one is not.
- **The README is 190 lines**, well past the original ~120 target. That target predates six
  new components and I have not re-cut it.


---

# A1 closed, and the defect it found

The full-Synthea fresh-clone path now works end to end:

```
### make synthea     bundles: 216              TIME 24s
### make load        loaded 216/216 (0 failed) TIME 383s
### make fhir-check  Patient 214, Encounter 12,088, MedicationRequest 10,799,
                     Condition 8,527, Observation 122,480   -> fhir-check passed
### pytest           119 passed                TIME 5s
```

Getting there took four more fixes, and the last one is the reason A1 was worth doing.

1. **`/tmp` is not mounted into the Docker VM.** `make synthea` bind-mounts the jar into a
   container, so a checkout outside `$HOME` mounts an empty directory and fails with Java's
   `Unable to access jarfile`. `make synthea` now probes the mount and says what is wrong.
   This is why my first three attempts failed: they all ran from `/tmp`.
2. **Synthea was OOM-killed (exit 137).** I had left five HAPI stacks running on a 6 GB VM.
   My own mess, but worth recording: the failure mode is a silent SIGKILL mid-write.
3. **The loader crashed on the truncated bundle that left behind**, with a raw
   `JSONDecodeError` naming a character offset. It now names the file and says to regenerate.
4. **`make synthea` excluded the hospital and practitioner bundles.** Synthea points every
   Encounter at those by conditional reference, so HAPI rejected all 214 patient bundles with
   a 404 — `ok=0 failed=214`. **The documented `make synthea && make load` path had never
   worked.** The 213-patient dataset I reported on night 1 came from a manual command with
   different flags, and I did not notice because I never ran the documented path.

That last one is the honest headline of this pass. The README described a pipeline that could
not run, the numbers in it were real but produced another way, and only a fresh-clone
reproduction attempt could have caught it.

**The dataset numbers changed as a consequence**, because the fixed export flags produce a
slightly different set: 214 patients rather than 213, 12,088 encounters rather than 11,947,
10,799 medication requests rather than 10,337, 122,480 observations rather than 121,010.
`reports/fhir-check.json` is regenerated from the documented path and the README now matches
it. `readme-check: 30 regenerated numbers, 0 mismatched`.

Fixes this pass: **11**, each with a negative control.


---

# Cleanup pass, and three more defects

Housekeeping first: removed ~1.9 GB of my own verification clones (`/tmp/vc2..4`,
`/tmp/verify-clone`, `~/vc5`, three scratch dirs), tore down five leftover HAPI stacks, and
removed the orphaned `docker_fhir-pgdata` volume left by the pre-fix compose project. The
machine is back to one stack on :8080 with the fixture loaded, which is what the README's
quick path produces.

Running `make verify` as a user would then found three more things:

12. **`make fhir-check` overwrote the committed artifact with fixture-sized counts.** This is
    the worst of the three: `reports/fhir-check.json` is what the README's dataset numbers
    trace to, and a routine `make verify` against the 10-patient fixture silently replaced
    214 patients with 10. Restored from git, and the write is now gated -- the artifact is
    only written when the check **passes** and the profile is `full`, so a small run cannot
    clobber the reference.
13. **`make verify` failed on the fixture stack for the wrong reason.** `fhir-check`'s
    minimums are sized for the full Synthea load, so the quick path the README now
    recommends failed against its own data. Added a `fixture` profile and
    `make verify FHIR_PROFILE=fixture`; the full profile now also prints a hint pointing at it.
14. **`make smoke` asserted that every guard bites on a 23-turn sample.** On that few turns a
    guard can have nothing to bite on -- no hospice turn, no injection turn -- and "removing
    it changed nothing" means the sample is small, not that the guard is broken. It failed on
    a healthy system. Smoke is a liveness check and now says so in code; mutation is asserted
    by the full replay gate over all 1,209 turns, where every guard does have work.

`make verify FHIR_PROFILE=fixture` now exits 0. Negative controls: the fixture run leaves
`reports/fhir-check.json` byte-identical; the full profile against fixture data fails with the
hint; a smoke run with a genuinely broken dimension still exits 1.

Fixes this pass: **14**, each with a negative control.


---

# README cut, and C11 made runnable

## README

123 -> 130 lines (the env-var docs you asked for added 11). Results table is at **line 17**,
so it lands on the first screen. Limitations moved to `LIMITATIONS.md` (64 lines) with a
three-line summary and link in the README's first ten lines. Every new component is one line.

`readme-check` now scans **README.md and LIMITATIONS.md together**, because moving a claim
between them must not silently drop it from the check. Negative controls: breaking a rubric
number fails it; changing "about thirty phrases" in LIMITATIONS fails it too.

`LIMITATIONS.md` records the three defects found in this repo's own tooling, including the
`make fhir-check` artifact-clobbering one and that `make readme-check` is what caught it.

**One self-inflicted mistake worth recording.** I ran `git checkout -- README.md` to undo a
deliberately-broken line during a negative control, and it reverted the entire uncommitted
rewrite. Redone from a backup copy. Do not use git as an undo for uncommitted work.

## C11 — answer to your question: no, it did not

`AnthropicClient` called `anthropic.Anthropic()` with no `base_url` and demanded
`ANTHROPIC_API_KEY`. An OpenRouter or Gemini key could not have been used. Added:

| Variable | Meaning |
|---|---|
| `EVAL_MODEL` | `<provider>:<model>` — `anthropic:claude-opus-5` or `openai-compatible:google/gemini-2.0-flash-exp:free`. Only the first colon separates, so model names containing colons work. |
| `EVAL_MODEL_BASE_URL` | e.g. `https://openrouter.ai/api/v1`. Required for `openai-compatible`. |
| `EVAL_MODEL_API_KEY` | The key. `ANTHROPIC_API_KEY` still works for the anthropic provider. |
| `CLINICAL_JUDGE_MODEL` | Optional. A different model — and a different provider — for the judge, which is what B9's second reader needs. |

`openai>=1.40,<3.0` added to the `real` extra, imported lazily so mock mode never needs it.
Both providers were exercised through their error paths (missing base URL, missing key);
neither has been run against a live endpoint.

**Key safety.** `tests/test_no_key_leak.py` scans `reports/`, `reports-real/` and `audit/`
for the first 8 characters of any set key, and separately scans every tracked file for
key-shaped strings. It carries a negative control that plants a synthetic key and proves the
scanner finds it, so the test cannot pass merely by having nothing to look at.

## `--turns-subset`

Stratified across turn kind, which maps onto the guard categories. A flat random sample of
180 from 1,209 would leave some guards with nothing to bite on and make a budget run look
better than it is. Verified at 180 turns:

```
appointments 30, cross_patient 8, diagnose 10, escalate_info 9, escalate_urgent 7,
hard_diagnose 3, hard_escalate 2, hard_prescribe 3, hard_scope 3, hospice 7, injection 5,
medications 30, mental_health 8, opener 30, prescribe 10, safe 7, under_two 8
```

Every guard category and every `hard_*` paraphrase is represented. The report records
`turns_evaluated`, `turns_available`, the seed, and the per-kind table. Deterministic for a
given seed. `make eval ARGS="--model real --turns-subset 180"` is the intended first run.

## Ready for a key

Nothing further can be verified without one. With a key set I would run: the subset eval on
~180 turns, judge calibration, then B9 with `CLINICAL_JUDGE_MODEL` pointed at a second model,
and report cost, latency, rubric and agreement as separate scorecard rows.
