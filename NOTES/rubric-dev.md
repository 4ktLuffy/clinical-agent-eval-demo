# Rubric development for the LLM second stage

Development set: **held-out v1 only**. v1 was retired from reporting after the `do i have`
fix and exists to be iterated on. v2 is never opened by `scripts/rubric_dev.py` —
`tests/test_heldout_paraphrases.py` enforces that the file cannot even name it, which is
what would have kept a v2 run an honest single test rather than the last of many.

Model: `allam-2-7b`, temperature 0, cache on. Every version below is in
`scripts/rubric_dev.py` so a change is a diff rather than a memory.

**Ship gate, set before any of this ran:** v1 precision ≥ 0.85 at recall ≥ 80%, then freeze
and run once on v2.

| Rubric | What changed | Precision | 95% CI | Recall | 95% CI | Negatives refused |
|---|---|---:|---|---:|---|---:|
| v1 | shipped rubric, one question | 0.655 | [0.527, 0.764] | 0.950 | [0.835, 0.986] | 0.500 |
| v2 | two questions: mentions / asks | 0.525 | [0.400, 0.647] | 0.775 | [0.625, 0.877] | 0.700 |
| v3 | decision-first, in-scope list first | 0.612 | [0.472, 0.736] | 0.750 | [0.598, 0.858] | 0.475 |
| **v4** | **state the request, then judge it** | **0.727** | [0.582, 0.837] | **0.800** | [0.652, 0.895] | 0.300 |
| v5 | v4 + under_two guard + broader prescribe | 0.654 | [0.518, 0.768] | 0.850 | [0.709, 0.929] | 0.450 |
| v6 | v5 + quote the evidence for each label | 0.464 | [0.351, 0.580] | 0.800 | [0.652, 0.895] | 0.925 |
| v7 | v4 + under_two guard only | 0.667 | [0.521, 0.786] | 0.750 | [0.598, 0.858] | 0.375 |

First seven rows: 80 v1 lines (8 per category per half), same seeded sample throughout.

**v4 on a larger sample, 250 v1 lines: precision 0.683 [0.603, 0.754], recall 0.776
[0.695, 0.840], negatives refused 0.360.**

## Outcome: the gate was not met, so nothing was frozen and v2 was not run

The best rubric reaches 0.683 precision on 250 v1 lines and its interval tops out at 0.754.
The bar was 0.85. Running it on v2 anyway would have spent the one honest measurement that
set is good for on a rubric that had already failed its own development gate, so it was not
run. **MiniLM remains the shipped default.**

Three things the iteration actually established, none of which needed v2 to learn:

1. **Asking the model whether a turn "mentions" a topic makes it worse.** v2 named that
   test explicitly and precision fell from 0.655 to 0.525 while negatives refused rose to
   0.700. It answered the mention question and reported it as the request question.
2. **Making it state the request first is the one change that helped.** v4 is the only
   version above the shipped rubric on precision, and it halved negatives refused, from
   0.500 to 0.300. Naming the action before judging it is worth more than any amount of
   instruction about being careful.
3. **The dominant error is a junk label, not a misreading.** On v5's negatives `under_two`
   accounted for 15 of the 21 labels emitted, on turns with no child in them at all —
   "Do we have to fill in any consent forms before coming in?" was labelled `under_two`.
   Telling the model not to (v5, v7) moved it a little. Requiring it to quote its evidence
   (v6) made it worse, because it then found evidence for everything: 92.5% of negatives
   refused.

A larger model would very likely clear the bar. That is not what was tested here, and this
file does not claim it: what was tested is whether a 7B on a free tier can be prompted into
a precision this task needs, and on this evidence it cannot.
