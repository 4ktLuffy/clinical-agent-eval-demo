# Every number, and what regenerates it

`make readme-check` diffs a set of figures against committed artifacts and fails on any
drift. `make number-audit` then checks that *every remaining* number in `README.md`,
`FINDINGS.md` and `LIMITATIONS.md` is accounted for: either it was one of those diffed
values, or it sits in a block marked `(manual: <command>)`, or it appears below on a row
naming the command that reproduces it.

A row here is stricter than an inline marker. A marker covers a whole paragraph; a row has
to name the individual figure and its command. This file exists so the first screen of the
README can read as prose without any number on it going undeclared.

## The headline pair — never quote either half alone

| Figure | Value | Regenerate |
|---|---|---|
| Held-out v2, shipped stage, recall | 51.0% [0.460, 0.560] | `python scripts/heldout_recall.py local` |
| Held-out v2, shipped stage, precision | 0.886 [0.838, 0.922] | `python scripts/heldout_recall.py local` |
| Held-out v2, shipped stage, refuses in-scope | 6.2% | `python scripts/heldout_recall.py local` |
| In-repo turns, same guardrail, recall | 82.7% | `make eval` |
| In-repo turns, same guardrail, precision | 1.000 | `make eval` |
| Held-out set size | 382 positives, 405 negatives | `python scripts/heldout_recall.py local` |

82.7% is measured on turns written beside the table that scores them. The distance between
it and 51.0% is the first finding in [`FINDINGS.md`](FINDINGS.md), not a rounding error.

## Guardrail stages on held-out v2

| Figure | Value | Regenerate |
|---|---|---|
| Phrase table alone, recall | 8.1% [0.058, 0.113] | `python scripts/heldout_recall.py none` |
| Phrase table alone, precision | 0.674 [0.530, 0.791] | `python scripts/heldout_recall.py none` |
| Phrase table alone, refuses in-scope | 3.7% | `python scripts/heldout_recall.py none` |
| + `allam-2-7b`, recall | 91.9% [0.887, 0.942] | `python scripts/heldout_recall.py local+llm:allam-2-7b` |
| + `allam-2-7b`, precision | 0.641 [0.599, 0.680] | `python scripts/heldout_recall.py local+llm:allam-2-7b` |
| + `allam-2-7b`, refuses in-scope | 48.6% | `python scripts/heldout_recall.py local+llm:allam-2-7b` |
| Recall gained by the LLM stage | 41 points | `python scripts/heldout_recall.py local+llm:allam-2-7b` |
| Intervals throughout | 95% Wilson | `pytest tests/test_stats.py` |

## Rubric and dataset

| Figure | Value | Regenerate |
|---|---|---|
| Rubric turns | 1,209 | `make eval` |
| Rubric dimensions | 98.3%–100.0% | `make eval` |
| Dataset | 214 patients, 12,088 encounters, 122,480 observations | `make fhir-check` |
| Tests | 206, 0 skipped with FHIR up | `pytest` |

## Everything else

Per-category and per-register held-out rows, the model sweep, injection rates, judge kappa,
latency percentiles and the rubric-development log all carry their own
`(manual: <command>)` markers in [`LIMITATIONS.md`](LIMITATIONS.md), beside the numbers
themselves. `make number-audit` fails if any of them loses its command.

## Caveats that travel with these numbers

- Held-out labels are **unreviewed**: assigned by the generating model, not a human.
- The live canary has **never run**; it needs a repo secret that does not exist.
- `compound-mini` in the sweep is 250/279 turns, on free-tier daily limits.
- Judge kappa at n=11 establishes nothing either way; n≈88 would be needed.
