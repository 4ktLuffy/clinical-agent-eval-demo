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
from eval.stats import agreement, bucket, cohens_kappa, kappa_interval, scored

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


def load_labels(path: Path) -> dict[str, tuple[float | None, float | None]]:
    """Hand labels for the open-ended turns, as `turn_id,faithfulness,citation_quality`.

    A blank cell is None, not zero: an unfilled sheet must make kappa refuse to compute
    rather than quietly score the judge against a column of zeros.
    """
    import csv

    out: dict[str, tuple[float | None, float | None]] = {}
    # Comment lines are stripped before parsing: csv.DictReader takes its header from the
    # first line it is given, so a leading comment would become the fieldnames and every
    # lookup would silently return None -- an unreadable sheet that looks like a blank one.
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    if reader.fieldnames is None or "turn_id" not in reader.fieldnames:
        raise ValueError(f"{path} has no turn_id column; found {reader.fieldnames}")
    for row in reader:
        turn_id = (row.get("turn_id") or "").strip()
        if not turn_id:
            continue

        def cell(name: str, _row=row) -> float | None:
            raw = (_row.get(name) or "").strip()
            return float(raw) if raw else None

        out[turn_id] = (cell("faithfulness"), cell("citation_quality"))
    return out


def evaluate(
    turns: list[dict],
    mode: str,
    guardrail: bool,
    out_dir: Path,
    sample_rate: float,
    judge_mode: str | None = None,
    labels_path: Path | None = None,
) -> dict[str, Any]:
    scripts = {t["turn_id"]: t["mock_draft"] for t in turns}
    corpus = Corpus.load(ROOT / "data" / "corpus")
    client = build_client(mode, scripts)
    judge = build_judge(judge_mode or mode)
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

    hand_labels = load_labels(labels_path) if labels_path else None
    judged, judge_scores, rule_scores, label_faith, label_cite = [], [], [], [], []
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
        if hand_labels is not None:
            hand = hand_labels.get(turn["turn_id"], (None, None))
            label_faith.append(hand[0])
            label_cite.append(hand[1])
        else:
            label_faith.append(turn["labels"]["faithfulness_label"])
            label_cite.append(turn["labels"]["citation_quality_label"])

    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    faithfulness = mean([s.faithfulness for s in judge_scores])
    citation_quality = mean([s.citation_quality for s in judge_scores])
    citation_presence = (
        sum(1 for r in results if r.used_corpus and r.citations)
        / max(1, sum(1 for r in results if r.used_corpus))
    )

    # Calibration is the judge against reference labels assigned by an AI reader -- not a
    # clinician, and not the author -- reading each answer next to the chunks it retrieved.
    # Those labels came from the same model that wrote the scripted drafts and designed the
    # rule judge, so they are provisional rather than an independent reference.
    # Inter-judge agreement is a different, weaker thing and is never reported as calibration.
    # Turns where the judge returned nothing parseable carry no opinion and are excluded
    # from calibration, then reported separately. Counting a crash as a score of 0.0 made
    # kappa look worse than the judge actually was.
    unparseable = [t for t, s in zip(judged, judge_scores) if not getattr(s, "valid", True)]
    if unparseable:
        keep = [i for i, s in enumerate(judge_scores) if getattr(s, "valid", True)]
        judged = [judged[i] for i in keep]
        judge_scores = [judge_scores[i] for i in keep]
        rule_scores = [rule_scores[i] for i in keep]
        label_faith = [label_faith[i] for i in keep]
        label_cite = [label_cite[i] for i in keep]

    calibration = inter_judge = None
    if judged and all(x is not None for x in label_faith):
        jf = [bucket(s.faithfulness) for s in judge_scores]
        jc = [bucket(s.citation_quality) for s in judge_scores]
        # Per-turn detail, not just the aggregate. A kappa of 0.00 says the judge is at
        # chance; it does not say which answers it read differently from the label, and that
        # is the part a person needs in order to decide who was right.
        disagreements = [
            {
                "turn_id": turn_id,
                "judge_faithfulness_raw": round(score.faithfulness, 3),
                "judge_faithfulness_bucketed": bucket(score.faithfulness),
                "label_faithfulness": label_f,
                "delta": round(abs(bucket(score.faithfulness) - label_f), 3),
                "judge_citation_bucketed": bucket(score.citation_quality),
                "label_citation": label_c,
                "citation_delta": round(abs(bucket(score.citation_quality) - label_c), 3),
                "judge_rationale": score.rationale[:200],
            }
            for turn_id, score, label_f, label_c in zip(
                judged, judge_scores, label_faith, label_cite
            )
        ]
        calibration = {
            "judge": judge.name,
            "n": len(judged),
            "label_source": str(labels_path) if labels_path else "ai-reader (data/turns.json)",
            "run_date": date.today().isoformat(),
            "unparseable_turns": unparseable,
            "per_turn": disagreements,
            "over_half_point": [d for d in disagreements
                                if d["delta"] > 0.5 or d["citation_delta"] > 0.5],
            "faithfulness": {
                "kappa": cohens_kappa(jf, label_faith),
                "kappa_ci": kappa_interval(jf, label_faith),
                "agreement": agreement(jf, label_faith),
            },
            "citation_quality": {
                "kappa": cohens_kappa(jc, label_cite),
                "kappa_ci": kappa_interval(jc, label_cite),
                "agreement": agreement(jc, label_cite),
            },
        }
        # Gated on the judge, not the drafting client: --judge real runs an LLM judge
        # over mock drafts, and that row still has a rule judge to disagree with.
        if (judge_mode or mode) == "real":
            rf = [bucket(s.faithfulness) for s in rule_scores]
            rc = [bucket(s.citation_quality) for s in rule_scores]
            inter_judge = {
                "faithfulness": {
                    "kappa": cohens_kappa(jf, rf),
                    "agreement": agreement(jf, rf),
                },
                "citation_quality": {
                    "kappa": cohens_kappa(jc, rc),
                    "agreement": agreement(jc, rc),
                },
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
        "calibration": calibration,
        "inter_judge_agreement": inter_judge,
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
    if r["calibration"]:
        c = r["calibration"]
        lines += [
            "",
            "### Judge calibration",
            "",
            f"Judge `{c['judge']}` against reference labels assigned by an AI reader -- not "
            f"a clinician, and not the author -- reading each answer next to its retrieved "
            f"chunks, on the 0 / 0.5 / 1 scale. n={c['n']}, run {c['run_date']}."
            + (f" {len(c['unparseable_turns'])} turn(s) excluded because the judge returned "
               f"unparseable output: {', '.join(c['unparseable_turns'])}."
               if c.get("unparseable_turns") else ""),
            "",
            "These labels are provisional: they came from the same model that wrote the "
            "scripted drafts and designed the rule judge, so they are not an independent "
            "reference. See NOTES/labeling-sheet.csv for a blank sheet for a human pass.",
            "",
            "| Dimension | Cohen's kappa (95% bootstrap) | Raw agreement |",
            "|---|---:|---:|",
            f"| faithfulness | {c['faithfulness']['kappa']:.2f} "
            f"[{c['faithfulness'].get('kappa_ci', (0, 0))[0]:.2f}, "
            f"{c['faithfulness'].get('kappa_ci', (0, 0))[1]:.2f}] | "
            f"{_pct(c['faithfulness']['agreement'])} |",
            f"| citation quality | {c['citation_quality']['kappa']:.2f} "
            f"[{c['citation_quality'].get('kappa_ci', (0, 0))[0]:.2f}, "
            f"{c['citation_quality'].get('kappa_ci', (0, 0))[1]:.2f}] | "
            f"{_pct(c['citation_quality']['agreement'])} |",
            "",
            "n=11 and the faithfulness labels are skewed to one level, so kappa is unstable "
            "here and is worth reading next to the raw agreement rather than alone.",
        ]
        big = c.get("over_half_point") or []
        lines += ["", "#### Judge and label disagree by more than 0.5", ""]
        if not big:
            lines.append("None.")
        else:
            lines += ["| Turn | Judge faith | Label faith | Judge cite | Label cite | Judge rationale |",
                      "|---|---:|---:|---:|---:|---|"]
            lines += [
                f"| `{d['turn_id']}` | {d['judge_faithfulness_bucketed']} | {d['label_faithfulness']} "
                f"| {d['judge_citation_bucketed']} | {d['label_citation']} | {d['judge_rationale'][:90]} |"
                for d in big
            ]
    if r["inter_judge_agreement"]:
        i = r["inter_judge_agreement"]
        lines += [
            "",
            "Inter-judge agreement (LLM judge vs the deterministic rule judge on the same "
            f"answers) -- not a calibration number: faithfulness kappa "
            f"{i['faithfulness']['kappa']:.2f}, citation quality kappa "
            f"{i['citation_quality']['kappa']:.2f}.",
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
    parser.add_argument("--judge", choices=("mock", "real"), default=None,
                        help="judge independently of the drafting client, so a judge row "
                             "can be measured against the same drafts")
    parser.add_argument("--sample-rate", type=float, default=1.0)
    parser.add_argument("--turns", type=Path, default=ROOT / "data" / "turns.json")
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--labels", type=Path, default=None,
                        help="CSV of hand labels (turn_id,faithfulness,citation_quality) "
                             "to compute kappa against instead of the AI-reader labels")
    args = parser.parse_args(argv)

    turns = json.loads(args.turns.read_text(encoding="utf-8"))
    report = evaluate(
        turns,
        mode=args.model,
        guardrail=not args.no_guardrail,
        judge_mode=args.judge,
        labels_path=args.labels,
        out_dir=args.out,
        sample_rate=args.sample_rate,
    )
    print((args.out / "scorecard.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
