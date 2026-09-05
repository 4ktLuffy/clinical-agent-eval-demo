"""Daily canary: replay a fixed 20-turn set against the live provider and diff.

What is compared, and why it can be compared at all: refusal and escalation are decided by
the guardrail reading the PATIENT's turn, so they do not depend on which model drafted the
reply. That is a measured property of this system, not an assumption -- the real-model runs
reproduce the mock confusion matrices cell for cell. It is what makes a committed baseline
meaningful against a provider whose weights can change under us.

Latency is different: it is machine- and provider-dependent, so it is judged against the
anomaly rules rather than against a stored number.

Fails on any refusal or escalation change, or latency outside the rules. Commits nothing;
writes a diff for upload.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.guardrail import classify  # noqa: E402
from clinical_agent.rag import Corpus, retrieval_threshold  # noqa: E402
from eval.conversation_run import stratified_subset  # noqa: E402
from clinical_agent.telemetry import AnomalyThresholds  # noqa: E402

BASELINE = ROOT / "reports" / "canary-baseline.json"
TURNS = 20
SEED = 20260906
PROMPT = ("You are a clinical call handler. Answer the caller in two sentences, using only "
          "the context.\n\nContext:\n{context}\n\nCaller: {turn}\nAnswer:")


def fixed_turns() -> list[dict]:
    conversations = json.loads((ROOT / "data" / "conversations.json").read_text())
    subset, _ = stratified_subset(conversations, TURNS, SEED)
    return [{"id": t["turn_id"], "text": t["text"]}
            for c in subset for t in c["turns"]][:TURNS]


def run(model: str | None) -> dict:
    corpus = Corpus.load(ROOT / "data" / "corpus")
    client = None
    if model:
        import openai

        client = openai.OpenAI(base_url=os.environ.get("EVAL_MODEL_BASE_URL", ""),
                               api_key=os.environ.get("EVAL_MODEL_API_KEY", ""))
    rows, latencies = [], []
    for turn in fixed_turns():
        hits = corpus.retrieve(turn["text"], k=4)
        kept = [h for h in hits if h.score >= retrieval_threshold()]
        context = "\n".join(f"[{h.chunk.chunk_id}] {h.chunk.text}" for h in kept) or "none"
        started = time.perf_counter()
        if client is None:
            draft = "Thanks for calling. I have your record open and can help with that."
        else:
            response = client.chat.completions.create(
                model=model, temperature=0, max_tokens=400,
                messages=[{"role": "user",
                           "content": PROMPT.format(context=context, turn=turn["text"])}])
            draft = (response.choices[0].message.content or "").strip()
        latencies.append((time.perf_counter() - started) * 1000)
        decision = classify(turn["text"], draft, hits[0].score if hits else 0.0, None)
        rows.append({
            "id": turn["id"],
            "refused": decision.refused,
            "refusal_categories": sorted(decision.refusal_categories),
            "clinical_escalation": decision.clinical_escalation,
            "operational_escalation": decision.operational_escalation,
        })
    ordered = sorted(latencies)
    return {
        "run_date": date.today().isoformat(),
        "model": model or "mock",
        "turns": len(rows),
        "rows": rows,
        "latency_p50_ms": ordered[len(ordered) // 2] if ordered else None,
        "latency_p95_ms": ordered[min(int(0.95 * len(ordered)), len(ordered) - 1)] if ordered else None,
    }


def diff(baseline: dict, current: dict) -> list[str]:
    """Only the model-independent fields. Latency is judged by the rules, not by equality."""
    changes = []
    before = {r["id"]: r for r in baseline["rows"]}
    for row in current["rows"]:
        was = before.get(row["id"])
        if was is None:
            changes.append(f"{row['id']}: not in the baseline")
            continue
        for field in ("refused", "refusal_categories", "clinical_escalation",
                      "operational_escalation"):
            if was[field] != row[field]:
                changes.append(f"{row['id']}.{field}: {was[field]!r} -> {row[field]!r}")
    missing = set(before) - {r["id"] for r in current["rows"]}
    changes += [f"{turn_id}: missing from this run" for turn_id in sorted(missing)]
    return changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("CANARY_MODEL", ""))
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports-canary")
    args = parser.parse_args(argv)

    current = run(args.model or None)
    if args.write_baseline:
        BASELINE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"wrote baseline: {BASELINE} ({current['turns']} turns)")
        return 0

    if not BASELINE.exists():
        print("no baseline committed; run with --write-baseline", file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changes = diff(baseline, current)

    # The same rule the load test uses: a p95 more than `latency_p95_multiple` times the
    # baseline p95, with a floor so a fast baseline cannot make every run an incident.
    thresholds = AnomalyThresholds()
    ceiling = max(baseline["latency_p95_ms"] * thresholds.latency_p95_multiple,
                  thresholds.latency_floor_ms)
    latency_breach = None
    if current["latency_p95_ms"] and current["latency_p95_ms"] > ceiling:
        latency_breach = (f"p95 {current['latency_p95_ms']:.0f} ms over the "
                          f"{ceiling:.0f} ms ceiling "
                          f"({thresholds.latency_p95_multiple}x baseline p95, "
                          f"floor {thresholds.latency_floor_ms:.0f} ms)")

    report = {**current, "baseline_date": baseline["run_date"], "changes": changes,
              "latency_breach": latency_breach,
              "status": "fail" if (changes or latency_breach) else "pass"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "canary-diff.json").write_text(json.dumps(report, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"canary {report['status']}: {len(changes)} decision change(s), "
          f"p50 {current['latency_p50_ms']:.0f} ms, p95 {current['latency_p95_ms']:.0f} ms")
    for change in changes[:10]:
        print(f"  {change}")
    if latency_breach:
        print(f"  {latency_breach}")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
