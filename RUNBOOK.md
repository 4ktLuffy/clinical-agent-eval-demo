# Go-live runbook

For the engineer standing up this agent against a customer's FHIR server. Written to be
followed at 6am by someone who did not build it.

Everything below assumes **synthetic data**. This system has never been run against a real
patient record and is not cleared to be.

---

## 1. Prerequisites

| Requirement | Check |
|---|---|
| Python 3.11+ | `python -V` |
| Docker with compose | `docker compose version` |
| FHIR R4 endpoint reachable | `curl -sf $FHIR_URL/metadata` returns 200 |
| Read/write scope on the endpoint | `Patient` read, `Appointment` create + update |
| Audit sink writable | `reports/fhir-audit.jsonl` path exists and is append-only |
| Model access (optional) | `ANTHROPIC_API_KEY` set, or the mock path is used and says so |

Set once for the session:

```bash
export FHIR_URL=https://<customer-fhir-host>/fhir
export CLINICAL_AGENT_FHIR_URL=$FHIR_URL
```

If the customer's server is behind mTLS or an auth proxy, terminate that in front of the
agent. This client sends no credentials of its own; that is deliberate.

---

## 2. Deploy

```bash
make fhir-up            # local stack only; skip against a customer endpoint
make synthea && make load   # local stack only
pip install -e ".[dev]"
```

Against a customer endpoint you deploy **only the agent**. Do not run `make load`, `make
synthea`, or `make clean-fhir` against a customer server. `clean-fhir` destroys a database
volume; it exists for the local stack and nothing else.

---

## 3. Pre-traffic verification

Run in this order. Each one gates the next. Stop at the first failure.

```bash
make fhir-check     # 1. is the data the shape the agent expects
make smoke          # 2. 20-turn replay through the guardrail
make replay         # 3. full set against the committed baseline
```

**1. `make fhir-check`** queries the endpoint for the resource types the agent reads and
fails if any is below the minimum in `scripts/fhir_check.py`. Adjust those minimums to the
customer's expected volumes before go-live; the defaults are sized for the local Synthea set.

**2. `make smoke`** runs about 20 turns end to end. It is a liveness check, not a regression
gate — too few turns for the rates to be comparable. It fails if any rubric dimension falls
below 80% or if any guard has stopped biting.

**3. `make replay`** runs all 1,174 turns against `reports/replay-baseline.json` and exits
non-zero if any dimension has fallen more than one point, or if removing any single guard no
longer degrades the dimension it protects.

Optionally, before a first go-live:

```bash
make loadtest       # 2,000 concurrent sessions, and proves all four detectors fire
```

---

## 4. What "green" means

All five must hold. Anything else is not green.

1. `make fhir-check` exits 0 and the capability statement names FHIR R4.
2. `make smoke` exits 0.
3. `make replay` exits 0 — no dimension below baseline by more than one point, every guard
   still biting.
4. `reports/fhir-audit.jsonl` has one line per FHIR access from the smoke run, each carrying
   `session_id`, `actor`, `patient_scope`, `operation`, `resource_type`, `outcome`.
5. Zero lines in that audit file with `outcome=blocked` that you did not cause yourself. A
   blocked line is a refused cross-patient access. During verification there should be none.

Record the four exit codes and the audit line count in the deployment ticket. "It looked
fine" is not a verification record.

---

## 5. Rollback

The agent is stateless apart from two things it writes: `Appointment` resources it creates,
and the audit log.

```bash
# 1. stop taking traffic (however the customer fronts it)
# 2. identify what this deployment wrote
grep '"operation": "create"' reports/fhir-audit.jsonl | tail -50
```

Each line carries the `resource_id`. To reverse a booking, cancel it rather than deleting it
— a cancelled Appointment is a record, a deleted one is a gap:

```bash
curl -X PUT "$FHIR_URL/Appointment/<id>" -H 'Content-Type: application/fhir+json' \
     -d '{"resourceType":"Appointment","id":"<id>","status":"cancelled", ...}'
```

**Never delete audit lines.** The file is append-only by design. If a rollback needs to be
explained later, that file is the only account of what happened.

Rolling back the code is `git checkout` of the previous tag and a redeploy. Do not roll back
`reports/replay-baseline.json` at the same time unless you intend to lower the bar.

---

## 6. On-call: anomaly response

The four detectors and what to do when each fires.

### `cross_patient_attempt`

**Page immediately.** This means a session tried to reach a resource outside its patient
scope. The attempt was refused and the resource was not modified — the enforcement is in
`fhir_client.py` and there is a test for it — but the attempt itself needs explaining.

1. `grep '"outcome": "blocked"' reports/fhir-audit.jsonl` — get `session_id` and `patient_scope`.
2. Establish whether it was a conversation-routing bug (the wrong patient bound to a session)
   or something reaching the tool layer with an id it should not have.
3. Do not clear the alert until you can say which.

### `refusal_rate_drift`

The guardrail has stopped firing at its usual rate. Most often a corpus or config change, not
an attack. A guardrail that goes quiet looks exactly like a quiet day, which is why this is
measured against the opening window rather than the running average.

1. `make smoke` — if a guard has stopped biting, it fails.
2. Compare the deployed guardrail tables against the last known-good commit.
3. If the drift is real and unexplained, stop traffic. An agent that has stopped refusing is
   worse than an agent that is down.

### `tool_error_rate_spike`

More than 5% of tool calls failing. Almost always the FHIR endpoint, not the agent.

1. `make fhir-check` — is the endpoint healthy at all?
2. Check the customer's FHIR server status before escalating to the agent team.
3. The agent degrades honestly here: a tool error escalates the turn to a human rather than
   inventing an answer. Traffic can usually continue while this is diagnosed.

### `latency_cliff`

Tail p95 more than 3x the opening p95. Compare like with like — this rule was wrong once in
exactly that way, and the note is in `detectors.py`.

1. Check whether the cliff is the FHIR endpoint or the model provider.
2. If it is the model, the mock path is not a fallback for production; reduce concurrency
   instead.
3. A 1.7x rise is drift, not a cliff, and deliberately does not page.

---

## 7. What this deployment will not do

State these to the customer before go-live, not after.

- It does not diagnose, prescribe, handle hospice, handle mental health disorders, or handle
  children under two. Those are refused, not attempted.
- It escalates to a human on urgent clinical signals rather than triaging them. **The
  escalation table is a fixture of about thirty phrases and is not a triage engine.**
- It cannot read or write another patient's record within a session. That is enforced by the
  process boundary, not by a prompt.
- Nothing identifying reaches the model or the logs: names, dates of birth, addresses,
  identifiers and contact details are tokenised first.
