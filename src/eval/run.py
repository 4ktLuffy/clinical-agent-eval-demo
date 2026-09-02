"""Run every turn through the agent, then score the run.

Refusal and both escalation axes are scored deterministically against the expected
labels in data/turns.json. Those labels are synthetic and were written by us; they are
not a clinical reference and nothing here should be read as one.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from clinical_agent.agent import Agent
from clinical_agent.guardrail import REFUSAL_CATEGORIES
from clinical_agent.llm import build_client
from clinical_agent.rag import Corpus
from clinical_agent.telemetry import (
    AnomalyThresholds,
    TelemetryLog,
    detect_anomalies,
    percentile,
    thresholds_table,
)
from clinical_agent.tools import EHRTools
from eval.judge import build_judge
from eval.stats import cohens_kappa, scored

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("retrieve", "tool", "draft", "guardrail")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ci(bounds: tuple[float, float]) -> str:
    return f"[{bounds[0] * 100:.1f}, {bounds[1] * 100:.1f}]"


def _row(name: str, s: dict) -> str:
    return (
        f"| {name} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} | "
        f"{_pct(s['precision'])} {_ci(s['precision_ci'])} | "
        f"{_pct(s['recall'])} {_ci(s['recall_ci'])} | {_pct(s['f1'])} |"
    )


HEADER = (
    "| Axis | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) | F1 |\n"
    "|---|---:|---:|---:|---:|---|---|---:|"
)


def evaluate(
    turns: list[dict],
    mode: str,
    guardrail: bool,
    out_dir: Path,
    sample_rate: float,
) -> dict[str, Any]:
    scripts = {t["turn_id"]: t["mock_draft"] for t in turns}
    corpus = Corpus.load(ROOT / "data" / "corpus")
    client = build_client(mode, scripts)
    judge = build_judge(mode)
    rule_judge = build_judge("mock")

    out_dir.mkdir(parents=True, exist_ok=True)
    telemetry = TelemetryLog(out_dir / "telemetry.jsonl")

    results = []
    with EHRTools() as tools:
        agent = Agent(client, corpus, tools, guardrail_enabled=guardrail)
        for turn in turns:
            result = agent.run_turn(turn)
            telemetry.record(result)
            results.append(result)
    telemetry.close()

    pred_refuse = [r.decision.refused for r in results]
    exp_refuse = [t["labels"]["should_refuse"] for t in turns]
    refusal = scored(pred_refuse, exp_refuse)

    per_category = {}
    for category in REFUSAL_CATEGORIES:
        per_category[category] = scored(
            [category in r.decision.refusal_categories for r in results],
            [category in t["labels"]["refusal_categories"] for t in turns],
        )

    clinical = scored(
        [r.decision.clinical_escalation for r in results],
        [t["labels"]["clinical_escalation"] for t in turns],
    )
    operational = scored(
        [r.decision.operational_escalation for r in results],
        [t["labels"]["operational_escalation"] for t in turns],
    )

    judged, judge_scores, rule_scores, expect_faithful = [], [], [], []
    for result, turn in zip(results, turns):
        # Judge only the open-ended, non-safety output: turns the guardrail left alone,
        # where the model's draft stands on its own as the answer. Scoring faithfulness on
        # a scripted refusal, or on a hand-off line that asserts nothing, measures nothing.
        if not (result.used_corpus and result.decision.reply_mode == "keep"):
            continue
        judged.append(result.turn_id)
        judge_scores.append(
            judge.score(result.draft, result.context, list(result.citations), result.chunk_texts)
        )
        rule_scores.append(
            rule_judge.score(result.draft, result.context, list(result.citations), result.chunk_texts)
        )
        expect_faithful.append(turn["labels"]["expect_faithful"])

    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    faithfulness = mean([s.faithfulness for s in judge_scores])
    citation_quality = mean([s.citation_quality for s in judge_scores])
    citation_presence = (
        sum(1 for r in results if r.used_corpus and r.citations)
        / max(1, sum(1 for r in results if r.used_corpus))
    )

    kappa = None
    if mode == "real" and judged:
        kappa = {
            "vs_rule_judge": cohens_kappa(
                [s.faithful for s in judge_scores], [s.faithful for s in rule_scores]
            ),
            "vs_expected_labels": cohens_kappa(
                [s.faithful for s in judge_scores], expect_faithful
            ),
            "n": len(judged),
            "judge": judge.name,
            "run_date": date.today().isoformat(),
        }

    latency = {
        "total": {
            "p50": percentile([r.total_ms for r in results], 0.50),
            "p95": percentile([r.total_ms for r in results], 0.95),
        }
    }
    for stage in STAGES:
        values = [r.stage_ms.get(stage, 0.0) for r in results]
        latency[stage] = {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}

    step = max(1, round(1 / sample_rate)) if sample_rate > 0 else 1
    sampled = telemetry.records[::step]
    alerts = detect_anomalies(sampled, AnomalyThresholds())

    misses = []
    for result, turn in zip(results, turns):
        labels, decision = turn["labels"], result.decision
        why = []
        if decision.refused != labels["should_refuse"]:
            why.append("refusal")
        if decision.clinical_escalation != labels["clinical_escalation"]:
            why.append("clinical escalation")
        if decision.operational_escalation != labels["operational_escalation"]:
            why.append("operational escalation")
        if why:
            misses.append({"turn_id": turn["turn_id"], "axes": why, "note": turn["note"]})

    report = {
        "model": client.name,
        "judge": judge.name,
        "guardrail": guardrail,
        "turns": len(turns),
        "run_date": date.today().isoformat(),
        "sample_rate": sample_rate,
        "sampled_turns": len(sampled),
        "refusal": refusal,
        "refusal_by_category": per_category,
        "clinical_escalation": clinical,
        "operational_escalation": operational,
        "faithfulness_mean": faithfulness,
        "citation_quality_mean": citation_quality,
        "citation_presence_rate": citation_presence,
        "judged_turns": len(judged),
        "kappa": kappa,
        "latency_ms": latency,
        "anomaly_thresholds": thresholds_table(),
        "anomalies": alerts,
        "expected_misses": misses,
    }
    (out_dir / "scorecard.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "scorecard.md").write_text(render(report, turns), encoding="utf-8")
    return report


def render(r: dict, turns: list[dict]) -> str:
    counts = {
        "refusal positives": sum(1 for t in turns if t["labels"]["should_refuse"]),
        "clinical escalation": sum(1 for t in turns if t["labels"]["clinical_escalation"]),
        "operational escalation": sum(1 for t in turns if t["labels"]["operational_escalation"]),
    }
    lines = [
        "# Scorecard",
        "",
        f"- model: `{r['model']}`  judge: `{r['judge']}`  guardrail: "
        f"`{'on' if r['guardrail'] else 'off'}`",
        f"- turns: {r['turns']} ("
        + ", ".join(f"{v} {k}" for k, v in counts.items())
        + f", {r['turns'] - sum(counts.values())} safe)",
        f"- run date: {r['run_date']}  sample rate: {r['sample_rate']} "
        f"({r['sampled_turns']} turns routed to the anomaly path)",
    ]
    if r["model"] == "mock":
        lines += [
            "",
            "Mock-path numbers measure **the pipeline, not model quality**: the drafts are "
            "scripted, so what is being exercised is retrieval, the tool seam, the guardrail "
            "and the scoring, not a model's judgement.",
        ]
    lines += [
        "",
        "The expected values these are scored against are **synthetic labels, written by "
        "us**. They are not a clinical reference.",
        "",
        "## Headline",
        "",
        HEADER,
        _row("Refusal (overall)", r["refusal"]),
        _row("Clinical escalation", r["clinical_escalation"]),
        _row("Operational escalation", r["operational_escalation"]),
        "",
        "## Refusal by category",
        "",
        "Five positives per category. These intervals are wide by construction: this table "
        "shows the harness works, not that the guardrail is good.",
        "",
        HEADER,
    ]
    for category, s in r["refusal_by_category"].items():
        lines.append(_row(f"`{category}`", s))
    lines += [
        "",
        "## Faithfulness and citations",
        "",
        f"- judge: `{r['judge']}` (scored on {r['judged_turns']} open-ended turns: the "
        "guardrail left the draft alone and it used corpus context)",
        f"- mean faithfulness: {r['faithfulness_mean']:.2f}",
        f"- mean citation quality: {r['citation_quality_mean']:.2f}",
        f"- citation presence rate: {_pct(r['citation_presence_rate'])}",
    ]
    if r["kappa"]:
        k = r["kappa"]
        lines += [
            "",
            f"- Cohen's kappa, LLM judge vs the deterministic rule judge on the same "
            f"answers: {k['vs_rule_judge']:.2f} (n={k['n']})",
            f"- Cohen's kappa, LLM judge vs our expected labels: "
            f"{k['vs_expected_labels']:.2f} (n={k['n']})",
            f"- judge model `{k['judge']}`, run {k['run_date']}",
        ]
    lines += ["", "## Latency", "", "| Stage | p50 ms | p95 ms |", "|---|---:|---:|"]
    for stage in ("total",) + STAGES:
        entry = r["latency_ms"][stage]
        lines.append(f"| {stage} | {entry['p50']:.1f} | {entry['p95']:.1f} |")
    lines += ["", "## Anomaly alerts", ""]
    lines += [f"- {a}" for a in r["anomalies"]] or ["- none"]
    lines += ["", "## Expected misses", ""]
    if r["expected_misses"]:
        for m in r["expected_misses"]:
            lines.append(f"- `{m['turn_id']}` ({', '.join(m['axes'])}): {m['note']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run")
    parser.add_argument("--model", choices=("mock", "real"), default="mock")
    parser.add_argument("--no-guardrail", action="store_true")
    parser.add_argument("--sample-rate", type=float, default=1.0)
    parser.add_argument("--turns", type=Path, default=ROOT / "data" / "turns.json")
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)

    turns = json.loads(args.turns.read_text(encoding="utf-8"))
    report = evaluate(
        turns,
        mode=args.model,
        guardrail=not args.no_guardrail,
        out_dir=args.out,
        sample_rate=args.sample_rate,
    )
    print((args.out / "scorecard.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
