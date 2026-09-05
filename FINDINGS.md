# Findings

**The guardrail scores 82.7% recall on the turns it was written alongside and 8.0%
[5.7, 11.2] on held-out paraphrases it has never seen.** Labels unreviewed — the held-out
categories were assigned by the generating model, not a human, and this figure will be
restated with strike counts once that review is done. Both numbers are real and measured
the same way; the difference is provenance. The 180-turn subset was written in this
repository beside the keyword table that scores it, so its 82.7% is partly a memory test.
The held-out set is 375 paraphrases, 60+ per refusal category, four registers, generated
by a model used in no stage here, with zero overlap against the tuned conversations and a
test that keeps it that way. Precision falls the same way: 1.000 in-repo against 0.600
[0.462, 0.724] over the held-out positives plus 394 in-scope negatives that share the
categories' topic vocabulary. Mental-health recall on held-out lines is 0 of 65. Twenty of
the 394 negatives are refused outright — hospice parking, bringing a baby to an
appointment, where to store a bottle — because the table matches a topic word and never
reads the request. Any in-repo evaluation number in this repository should be read as an
upper bound, and that is the finding: not that this guardrail is weak, but that the
harness reporting on it could not see the weakness until the evaluation data came from
somewhere else.

**A judge's token budget silently inflated its own agreement score by more than double.**
The LLM judge ran at `max_tokens=300`, sized for a non-reasoning model. `gpt-oss-120b`
spends 236 to 298 tokens reasoning before it emits anything, so its JSON was truncated
mid-object on 4 of 11 turns. Those turns were dropped as unparseable and kappa was computed
on the 7 that survived, reporting +0.42 where the full 11 give +0.19. The loss was not
random: the truncated turns were the long ones, so the drop removed exactly the cases the
judge found hardest. Nothing failed, no test went red, and the run exited zero. It was
caught because a 4-of-11 dropout looked wrong, not because anything reported it. Before an
earlier fix, those truncations had scored as confident 0.0 rather than being excluded at
all, which had pushed the same figure in the opposite direction.

**The guardrail's only model-facing check earned nothing.** The draft-side refusal table is
the one guard that reads what the model wrote rather than what the patient said. On a
180-turn real run with `gpt-oss-20b` it fired on 18 drafts, and all 18 were turns the
patient-side table had already refused: zero catches of its own. Reading all 18 by hand, 13
were the model correctly refusing, with the table matching a topic word such as "hospice"
or "take an extra dose" inside the refusal itself, and none contained diagnosis content.
The harness would have reported "18 unsafe drafts caught" — a materially false claim —
and did report exactly that until the drafts were read. The earlier real runs had not
persisted their drafts at all, so the question could not be asked of them.
