# Conversation eval

- conversations: 200  turns: 1209
- source: patients loaded in FHIR; the medications named are theirs
- judge: none. Every dimension is scored deterministically against the expected
  outcome recorded with the turn.
- run date: 2026-09-03

## Rubric

Turns tagged `hard_*` are paraphrases that carry no phrase from the guardrail's
tables. They are included on purpose: without them this table reads 100% across
the board, which would only be measuring that the generator and the matcher share
a trigger list. The gap below is the honest ceiling of a keyword guardrail.

| Dimension | Passed | Total | Rate | 95% CI |
|---|---:|---:|---:|---|
| `accurate_to_context` | 1209 | 1209 | 100.0% | [99.7, 100.0] |
| `in_scope` | 1188 | 1209 | 98.3% | [97.4, 98.9] |
| `escalated_when_warranted` | 1196 | 1209 | 98.9% | [98.2, 99.4] |
| `no_diagnosis` | 1189 | 1209 | 98.3% | [97.5, 98.9] |
| `no_prescription` | 1189 | 1209 | 98.3% | [97.5, 98.9] |
| `no_cross_patient_leak` | 1209 | 1209 | 100.0% | [99.7, 100.0] |
| `ignores_injected_instructions` | 1209 | 1209 | 100.0% | [99.7, 100.0] |

## Per-guard mutation

Each row removes one guard and re-runs the whole set. The dimension that guard
protects must get worse, or the guard is not doing the work the rubric credits.

| Guard removed | Dimension | Before | After | Dropped |
|---|---|---:|---:|:--:|
| `prescribe` | `no_prescription` | 98.3% | 93.0% | yes |
| `diagnose` | `no_diagnosis` | 98.3% | 92.6% | yes |
| `hospice` | `in_scope` | 98.3% | 94.5% | yes |
| `mental_health_treatment` | `in_scope` | 98.3% | 94.0% | yes |
| `under_two` | `in_scope` | 98.3% | 93.9% | yes |
| `clinical_escalation` | `escalated_when_warranted` | 98.9% | 89.7% | yes |
| `injection` | `ignores_injected_instructions` | 100.0% | 97.2% | yes |

## Latency (harness only, scripted drafts)

- p50 0.44 ms, p95 0.49 ms, p99 0.55 ms
