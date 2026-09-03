# Conversation eval

- conversations: 200  turns: 1174
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
| `accurate_to_context` | 1174 | 1174 | 100.0% | [99.7, 100.0] |
| `in_scope` | 1153 | 1174 | 98.2% | [97.3, 98.8] |
| `escalated_when_warranted` | 1154 | 1174 | 98.3% | [97.4, 98.9] |
| `no_diagnosis` | 1162 | 1174 | 99.0% | [98.2, 99.4] |
| `no_prescription` | 1155 | 1174 | 98.4% | [97.5, 99.0] |
| `no_cross_patient_leak` | 1174 | 1174 | 100.0% | [99.7, 100.0] |

## Per-guard mutation

Each row removes one guard and re-runs the whole set. The dimension that guard
protects must get worse, or the guard is not doing the work the rubric credits.

| Guard removed | Dimension | Before | After | Dropped |
|---|---|---:|---:|:--:|
| `prescribe` | `no_prescription` | 98.4% | 92.7% | yes |
| `diagnose` | `no_diagnosis` | 99.0% | 93.6% | yes |
| `hospice` | `in_scope` | 98.2% | 94.2% | yes |
| `mental_health_treatment` | `in_scope` | 98.2% | 93.2% | yes |
| `under_two` | `in_scope` | 98.2% | 93.4% | yes |
| `clinical_escalation` | `escalated_when_warranted` | 98.3% | 88.6% | yes |

## Latency (harness only, scripted drafts)

- p50 0.44 ms, p95 0.46 ms, p99 0.48 ms
