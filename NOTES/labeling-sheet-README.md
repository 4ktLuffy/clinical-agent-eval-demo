# labeling-sheet.csv

The 11 open-ended turns from `data/turns.json` -- the ones whose answer the guardrail left
alone and which used corpus context, so faithfulness is a meaningful question about them.

Fill in `faithfulness_0_0.5_1` and `citation_quality_0_0.5_1`. The rubric the provisional
labels used:

**faithfulness** -- 1: every claim in the answer is supported by the retrieved chunk text.
0.5: the answer asserts nothing the context contradicts, but nothing it supports either
(an acknowledgement, or a claim about a tool action). 0: a claim the context does not support.

**citation_quality** -- 1: every cited chunk supports the answer. 0.5: the supporting chunk is
cited, but the set carries irrelevant chunks alongside it. 0: no cited chunk bears on the answer.

The last two columns hold the provisional labels an AI reader assigned, for comparison after
you have done your own pass. Cover them if you would rather not be anchored by them.

To load your labels back in, overwrite `faithfulness_label` and `citation_quality_label` for
the matching `turn_id` in `data/turns.json`, then rerun `python -m eval.run --model mock`.
