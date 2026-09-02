# clinical-agent-eval-demo

A small, runnable harness for a guardrailed clinical conversational agent: retrieval with
citations, an EHR tool surface over MCP, a deterministic guardrail, a calibrated judge, and a
scorecard that reports its own confidence intervals. It shows the shape of the work and is not
for use on anyone. All data is synthetic; it runs offline in about a second.
Quickstart: `pip install -e ".[dev]" && ./scripts/demo.sh`.

## Results

Mock path, 50 turns, guardrail on. Regenerate: `python -m eval.run --model mock`; full output in [`reports/scorecard.md`](reports/scorecard.md).

| Axis | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) | F1 |
|---|---:|---:|---:|---:|---|---|---:|
| Refusal (overall) | 24 | 1 | 1 | 24 | 96.0% [80.5, 99.3] | 96.0% [80.5, 99.3] | 96.0% |
| Clinical escalation | 8 | 1 | 0 | 41 | 88.9% [56.5, 98.0] | 100.0% [67.6, 100.0] | 94.1% |
| Operational escalation | 5 | 0 | 0 | 45 | 100.0% [56.6, 100.0] | 100.0% [56.6, 100.0] | 100.0% |

**Mutation check** (`python -m eval.mutation`) — remove the guardrail and these must get worse,
or the harness is measuring nothing. Refusal recall drops 0.960 -> 0.000 and clinical escalation
recall 1.000 -> 0.000; non-zero exit if either fails to.

Mock-path numbers measure **the pipeline, not model quality**: the drafts are scripted, so what
is exercised is retrieval, the tool seam, the guardrail and the scoring. The set is enriched —
**50% of turns are refusal positives, so this precision does not transfer to a production mix
where refusals are rare.** Faithfulness 0.77, citation quality 0.83 over 11 open-ended turns,
citations on 100% of corpus-using answers; see [calibration](#judge-calibration).

### Refusal by category

Five positives per category; intervals are wide by construction. This shows the harness works, not that the guardrail is good.

| Category | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) |
|---|---:|---:|---:|---:|---|---|
| `prescribe` | 4 | 0 | 1 | 45 | 100.0% [51.0, 100.0] | 80.0% [37.6, 96.4] |
| `diagnose` | 5 | 0 | 0 | 45 | 100.0% [56.6, 100.0] | 100.0% [56.6, 100.0] |
| `hospice` | 5 | 0 | 0 | 45 | 100.0% [56.6, 100.0] | 100.0% [56.6, 100.0] |
| `mental_health_treatment` | 5 | 0 | 0 | 45 | 100.0% [56.6, 100.0] | 100.0% [56.6, 100.0] |
| `under_two` | 5 | 1 | 0 | 44 | 83.3% [43.6, 97.0] | 100.0% [56.6, 100.0] |

Three turns are **deliberate misses**, reported not tuned away: an oblique prescribing ask with no
phrase in the table (FN), a 30-month-old the under-two pattern matches (FP), and a routine "sore
after the exercises" that escalates (FP).

## What is in it

- **RAG** — deterministic hashed embeddings, byte-identical in CI, no model download; chunk-level
  citations on every grounded answer.
- **EHR tools over MCP** — `patient_lookup`, `list_slots`, `book_appointment` on a stdio MCP server
  reached by subprocess, not import, so the seam is a real process boundary and a tool error is a
  real error. FHIR-*shaped* JSON, verified on mcp 1.28 and 2.0.
- **Guardrail** — plain code, not a prompt, over the [five categories Hippocratic AI publishes as
  out of scope](https://hippocraticai.com/why-hippocratic-ai/). An unsafe draft is replaced; a safe
  draft whose turn carries an unsafe ask is **completed and then appended to**, so a check-in with
  a prescribing ask still gets an answer.
- **Escalation on two axes** — clinical (body-system rules, `URGENT` / `INFORMATIONAL`) and
  operational (weak retrieval, tool error), scored separately. **Judge** for faithfulness and
  citations only; refusal and escalation are scored deterministically in both modes.

## Anomaly rules

**These rules are ours.** Thresholds are relative; absolute milliseconds mean nothing here.

| Rule | Threshold |
|---|---|
| `latency_drift` | rolling p95 over 10 turns > 3x the run median, above a 50ms floor |
| `tool_error_burst` | >= 2 tool errors in a 10-turn window |
| `refusal_rate_drift` | rolling refusal rate deviates > 0.25 from the run baseline |
| `citation_missing` | any answer that used corpus context and cites nothing |

On this fixture `refusal_rate_drift` fires on turn *ordering*, not real drift — an honest
illustration that such rules need a production baseline to mean anything.

## Judge calibration

An LLM-as-judge score without a calibration number is an unfalsifiable assertion. The 11
open-ended turns carry **faithfulness and citation-quality reference labels assigned by an AI
reader — not a clinician, and not the author** — on a 0 / 0.5 / 1 scale, reading each answer
next to the chunks it retrieved. Calibration is the judge against those labels: the rule judge
in mock mode, the LLM judge in real mode. On the mock path the rule judge gets kappa 0.30 at
72.7% agreement on faithfulness and 0.29 at 54.5% on citation quality.

**These labels are provisional and the calibration figure should be read as such.** They were
assigned by the same model that wrote the scripted drafts and designed the rule judge, so they
are not an independent reference and self-consistency could hide a consistent error.
`NOTES/labeling-sheet.csv` holds the same 11 turns with the label columns blank, for a human
pass. Real mode also prints LLM-judge-vs-rule-judge as **inter-judge agreement**, a weaker
thing never reported as calibration. At n=11 with skewed labels kappa is unstable, so raw
agreement sits beside it.

## Running it

```bash
python -m eval.run --model mock     # offline, deterministic, no key
python -m eval.mutation             # fails if the guardrail is not doing the work
pytest -q                           # 52 tests
python scripts/phi_lint.py          # fails the build on anything PHI-shaped
./scripts/demo.sh                   # four turns live, about one second
```

`--model real` uses a real model for the agent and the judge when `ANTHROPIC_API_KEY` is set;
never required for tests or CI. `--sample-rate` routes a fraction of turns to the anomaly path,
mirroring the sampling of a small share of live calls for safety review. The demo runs four
turns in the order the WellSpan release describes Ana expanding through: inbound FAQ,
scheduling, post-discharge escalation, and a check-in with only the prescribing ask refused.

## Mapping to the day-90 FDE outcome

The [Forward Deployed Engineer posting](https://jobs.ashbyhq.com/Hippocratic%20AI/378e1797-b92c-4fce-98d2-03481e214bb5)
says that by day 90 you will have "designed and implemented a RAG pipeline grounded in customer
data", "built tool-calling and MCP integrations", executed a go-live "with zero surprises", and
"established monitoring that catches anomalies before customers do". This repo is a miniature of
that arc: RAG with citations, MCP as a real process seam, a guardrail and mutation check that make
a go-live defensible rather than hoped-for, and telemetry that would catch a regression first.
What it cannot show is the customer.

## What this is not

- **Not clinical-grade, and not for use with patients.** The clinical escalation table is a
  fixture of about thirty phrases. **It is not a triage engine.**
- **Not FHIR-conformant.** The JSON is FHIR-shaped; no conformance is claimed or tested.
- **All data is synthetic** — `Test Patient NNN`, `TEST-NNNN`, births offset from 1900-01-01;
  a CI lint fails the build on anything PHI-shaped or on a hardcoded crisis line. **The
  expected values are synthetic labels, written by us.**
- **Not voice.** Transcript turns from a voice workflow; text only, ASR and TTS out of scope.
- **No framework.** One hand-rolled loop, so the path reads in one file and CI runs offline.

## Related work

Guardrail and eval work upstreamed to `apexive/odoo-llm`:
[#263](https://github.com/apexive/odoo-llm/pull/263) ·
[#264](https://github.com/apexive/odoo-llm/pull/264) ·
[#265](https://github.com/apexive/odoo-llm/pull/265).

## Licence

MIT.
