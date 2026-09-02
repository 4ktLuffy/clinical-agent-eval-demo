# Recon — Hippocratic AI

Read 2026-09-02. Public pages only: hippocraticai.com, their Ashby board, the WellSpan
GlobeNewswire release, PR Newswire, medRxiv. Every claim below carries a URL. Where the
plan assumed something I could not verify, it says "not found" rather than filling the gap.

## What they say is hard — in their own words

- The day-90 outcome is stated as: "established monitoring that catches anomalies before
  customers do" — [FDE (Mid/Senior) JD](https://jobs.ashbyhq.com/Hippocratic%20AI/378e1797-b92c-4fce-98d2-03481e214bb5)
- Same JD, on go-live: "executed a production go-live with zero surprises"
- Senior FDE frames the risk side as: "anticipate failure modes, implement proactive
  monitoring" — [Senior FDE JD](https://jobs.ashbyhq.com/hippocratic%20ai/dc5d7d07-fba0-4ddc-a832-345deb09cc78)
- On why general benchmarks are not enough: "Traditional LLM benchmarking approaches
  provide very limited output coverage" — [RWE-LLM, medRxiv](https://www.medrxiv.org/content/10.1101/2025.03.17.25324157v1)
- Their Chief Science Officer, on the same point: "None of them measure what actually
  happens on a real patient call" — [Polaris 5.0 release](https://hippocraticai.com/hippocratic-ai-launches-polaris-5-0/)
- On which model errors matter: general models are "not clinically safe with significant
  performance regression on targeted medical tasks" — [Polaris 2.0](https://hippocraticai.com/polaris2/)
- On knowing when to stop: LLMs "are not good at identifying situations that require
  human intervention" — [Polaris 2.0 appendix](https://hippocraticai.com/polaris2/)

## Vocabulary — their exact terms, to reuse verbatim

| Concept | Their term | Source |
|---|---|---|
| Grounding | "RAG pipeline grounded in customer data" | FDE JD |
| Tool surface | "tool-calling and Model Context Protocol (MCP) architectures" | FDE JD |
| Integration targets | "EHRs (Epic, Cerner, Athena), data warehouses, operational tools" | FDE JD |
| Judging | "LLM-as-judge"; "calibrate the judge to have high correlation with human raters" | FDE JD; [Benchmarks](https://hippocraticai.com/benchmarks/) |
| Monitoring | "monitoring that catches anomalies before customers do" | FDE JD |
| Escalation | "clinical escalation"; "Escalations to Human Nurse"; "Kickout Evaluator" | [Safety](https://hippocraticai.com/safety/); Benchmarks |
| Escalation severity | `URGENT` vs `INFORMATIONAL` | Benchmarks |
| Safety label | `MUST_FLAG` | Benchmarks |
| Their label vocabulary | "Ground Truth Labeling"; "Scoring Rubric"; "Test Set Composition" | Benchmarks |
| Rater agreement | "inter-rater agreement (Fleiss' κ...)" | Benchmarks |
| Interval reporting | "Wilson score interval" | Benchmarks |
| Live QA | ".5%-1% Of all live calls are sampled for safety" | [Home](https://hippocraticai.com/) |
| Safety validation | "output testing rather than relying solely on input data quality" | RWE-LLM |
| Architecture | "constellation architecture"; "specialized support models" | [Research](https://hippocraticai.com/research/) |

## What their agents must not do

Published verbatim on the homepage, under "We will only create AI agents in areas we
believe generative AI can safely handle" — [hippocraticai.com](https://hippocraticai.com/):

- "We do not prescribe"
- "We do not diagnose"
- "We do not handle hospice"
- "We do not handle mental health disorders"
- "We do not handle kids under the age of two"

The RWE-LLM paper calls the product a "non-diagnostic AI Care Agent". The mental-health
line is narrower than it looks: the escalation benchmark still requires the agent to
detect suicidal ideation, give crisis resources, and hand off — it must "not attempt
therapy" (Benchmarks). So: detect and escalate, never treat.

## What their agents do — named task types

From the [agent catalogue](https://hippocraticai.com/) and the WellSpan release:

- Appointment Scheduling — "scheduling, confirming details, and completing pre-visit paperwork"
- Patient Intake History; Health Risk Assessment intake
- Post-discharge recovery support (pneumonia; lower-extremity joint replacement)
- Chronic disease check-in; medication and RPM adherence
- Screening outreach — colorectal, mammogram, flu vaccination
- Inbound FAQ and "doctor and location information on request" (WellSpan)

WellSpan's agent is named Ana. It handles "more than 160,000 patient calls per month" and
is expanding to "post-discharge follow-up and chronic disease check-in", with first
workflows being "outreach to patients with missed imaging appointments" —
[GlobeNewswire, 30 Jul 2026](https://www.globenewswire.com/news-release/2026/07/30/3336096/0/en/wellspan-expands-hippocratic-ai-partnership-to-support-clinical-operations-and-improve-patient-experience.html).

Everything they ship is real-time **voice**. Nothing public describes a text-chat agent.

## Day-90 FDE outcome

Important: the day-90 language is in the **FDE (Mid/Senior)** posting, not the Senior FDE
posting. Quoted in full so the README can map to it:

> "By day 90, you will have completed end-to-end ownership of your first AI deployment:
> designed and implemented a RAG pipeline grounded in customer data, built tool-calling
> and MCP integrations connecting our agents to customer systems (EHRs, data warehouses,
> operational tools), executed a production go-live with zero surprises, and established
> monitoring that catches anomalies before customers do."

The Senior FDE posting instead lists "What Success Looks Like", including "advanced LLM
techniques (multi-turn reasoning, complex RAG, LLM-as-judge)" and "anticipate failure
modes, implement proactive monitoring".

Both list LangChain/LangSmith as a basic qualification, and MCP + FHIR/HL7 as preferred.

## Scope changes recommended

Each is a yes/no for you. Numbered for reply.

1. **Guardrail refuses on their published list, not my two categories.** Implement all
   five: prescribe, diagnose, hospice, mental-health treatment, under-two. Uses their own
   words as the spec, and gives the confusion matrix five failure modes instead of one.

2. **Split escalation into clinical and operational, and label severity.** Their escalation
   is a named, taxonomised thing — the "Kickout Evaluator" "Determines clinical severity in
   the conversation", classifying `URGENT` vs `INFORMATIONAL`. Replace the plan's vague
   "low confidence → escalate" with two independent triggers: clinical (symptom pattern
   across body systems) and operational (weak retrieval, tool error). Score them separately.

3. **Judge only where they use a judge.** Their published methodology uses LLM-as-judge for
   "non-safety open-ended benchmarks" only; safety runs against labels their licensed
   clinicians annotate, and reports accuracy. So: deterministic label-based precision/recall for refusal and
   escalation, LLM-as-judge for faithfulness/citation quality only. In real mode, report
   judge-vs-label agreement (Cohen's κ) — earning their "calibrate the judge" language and
   making the mock-vs-real honesty structural rather than a disclaimer.

4. **Report Wilson score 95% CIs on every rate.** They do. At ~30 turns the intervals will
   be embarrassingly wide — which is the point, and says plainly that a 30-turn eval does
   not prove model quality. Costs about ten lines.

5. **Make the three demo flows mirror Ana's actual expansion path**: inbound FAQ answer
   with citation → appointment scheduling through MCP → post-discharge follow-up turn that
   trips clinical escalation. Currently the plan's third flow is a diagnosis refusal;
   suggest keeping that as a fourth, since refusal and escalation are different guardrails.

6. **Frame the turns as call transcript turns, not chat.** Their product is voice-only.
   Keep text (deterministic, CI-friendly, no audio deps), but name it honestly in the
   README: transcript-level evaluation of a voice workflow, ASR/TTS out of scope.

7. **Add a `--sample-rate` flag to the telemetry path.** They publish that ".5%-1% Of all
   live calls are sampled for safety". Cheap to implement, and it is a real operational
   practice rather than an invented one.

8. **Mutation check covers escalation recall too**, not just refusal, now that escalation
   is a separate axis.

9. **Do not adopt LangChain.** Both JDs name it, but a hand-rolled loop is more readable in
   ten minutes and makes the MCP seam visible. My recommendation is to stay hand-rolled and
   say why in one README line — but this one is genuinely arguable, so it is your call.

## Not found

- No engineering blog post from them on RAG chunking, MCP integration patterns, or how the
  guardrail is implemented. Their research output is mostly inference (KV-cache), speech,
  and benchmarks — [LLM Research](https://hippocraticai.com/llm-research/).
- No public technical detail on their EHR/FHIR integration: Epic/Cerner/Athena are named as
  integration targets, nothing about resource shapes or transport.
- No published anomaly-detection vocabulary beyond the JD's one clause. The specific alert
  rules in the plan (latency drift, tool-error burst, refusal-rate drift) are mine, not
  theirs, and the README will say so.
- No p50/p95 latency figures published. The only latency number is "1.5 seconds
  time-to-first-audio" for Polaris 5.0, which is not comparable to a text pipeline.
- No public technical detail on the "Hippocratic AI Orchestrator" named in the WellSpan
  release.
- The Junior FDE (Contract) posting returns "Page not found"; the board still counts one
  contract role. Treating it as unavailable rather than guessing at its content.
- The plan's "published case studies with numbers" — the case studies exist but sit behind
  gated forms. Headline figures appear on the homepage; I did not fill in any form.
