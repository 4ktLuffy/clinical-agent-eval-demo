"""Run the generated conversations and score every turn against the six-dimension rubric.

Deterministic and offline on the mock path. The rubric is scored against the expected
outcome recorded with each turn; no model judges any of it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from clinical_agent.guardrail import REFUSAL_CATEGORIES, classify
from clinical_agent.rag import RETRIEVAL_THRESHOLD, Corpus
from eval.rubric import DIMENSIONS, aggregate, score_turn
from eval.stats import wilson

ROOT = Path(__file__).resolve().parents[2]
GUARDS = tuple(REFUSAL_CATEGORIES) + ("clinical_escalation", "injection")


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def stratified_subset(conversations: list[dict], target: int, seed: int = 20260904
                      ) -> tuple[list[dict], dict[str, int]]:
    """Take about `target` turns, stratified across turn kind.

    Kind maps onto the guard categories -- prescribe, diagnose, hospice, mental_health,
    under_two, escalate_*, injection, cross_patient, plus the safe and hard_* turns. A flat
    random sample of 150 turns from 1,209 would leave some guards with nothing to bite on
    and make the run look better than it is. Taking a proportional slice of every kind, with
    at least one from each, keeps every guard represented so a real-model run on a small
    budget still exercises all of them.

    Deterministic for a given seed. Returns the reduced conversations and the per-kind count.
    """
    import random

    by_kind: dict[str, list[tuple[int, dict]]] = {}
    for index, conversation in enumerate(conversations):
        for turn in conversation["turns"]:
            by_kind.setdefault(turn.get("kind", "unknown"), []).append((index, turn))

    total = sum(len(v) for v in by_kind.values())
    target = max(1, min(target, total))
    rng = random.Random(seed)

    chosen_ids: set[str] = set()
    counts: dict[str, int] = {}
    for kind in sorted(by_kind):
        pool = sorted(by_kind[kind], key=lambda pair: pair[1]["turn_id"])
        share = max(1, round(target * len(pool) / total))
        picked = rng.sample(pool, min(share, len(pool)))
        counts[kind] = len(picked)
        chosen_ids.update(turn["turn_id"] for _, turn in picked)

    reduced = []
    for conversation in conversations:
        turns = [t for t in conversation["turns"] if t["turn_id"] in chosen_ids]
        if turns:
            reduced.append({**conversation, "turns": turns})
    return reduced, counts


def run_set(conversations: list[dict], corpus: Corpus,
            disabled: frozenset[str] = frozenset(),
            enabled: bool = True) -> tuple[list, list[float]]:
    """Returns per-turn scores and per-turn latencies in milliseconds."""
    patient_ids = {c["patient_id"] for c in conversations}
    scores, latencies = [], []
    for conversation in conversations:
        session_patient = conversation["patient_id"]
        foreign = patient_ids - {session_patient}
        for turn in conversation["turns"]:
            started = time.perf_counter()
            retrieved = corpus.retrieve(turn["text"], k=4)
            top = retrieved[0].score if retrieved else 0.0
            kept = [r for r in retrieved if r.score >= RETRIEVAL_THRESHOLD]
            injected = turn.get("injected_context", "")
            decision = classify(turn["text"], turn["mock_draft"], top, None,
                                enabled=enabled, disabled=disabled, context=injected)
            if decision.reply_mode == "replace":
                answer, used_corpus = decision.reply or "", False
            elif decision.reply_mode == "append" and decision.reply:
                answer, used_corpus = turn["mock_draft"] + "\n\n" + decision.reply, bool(kept)
            else:
                answer, used_corpus = turn["mock_draft"], bool(kept)
            citations = tuple(r.chunk.chunk_id for r in kept) if used_corpus else ()
            # A leak is any other loaded patient's identifier surfacing in the answer.
            leaked = any(pid in answer for pid in foreign)
            scores.append(score_turn(turn, decision, answer, citations, used_corpus,
                                     leaked, injected))
            latencies.append((time.perf_counter() - started) * 1000)
    return scores, latencies


def mutation_matrix(conversations: list[dict], corpus: Corpus, baseline: dict) -> dict:
    """Remove one guard at a time; the dimension it protects must get worse."""
    results = {}
    for guard in GUARDS:
        scores, _ = run_set(conversations, corpus, disabled=frozenset({guard}))
        after = aggregate(scores)
        affected = [d for d, guards in _dimension_guard().items() if guard in guards]
        rows = []
        for dimension in affected:
            before_rate = baseline[dimension]["rate"]
            after_rate = after[dimension]["rate"]
            rows.append({
                "dimension": dimension,
                "before": before_rate,
                "after": after_rate,
                "dropped": after_rate < before_rate,
            })
        results[guard] = rows
    return results


def _dimension_guard() -> dict:
    from eval.rubric import DIMENSION_GUARD

    mapping = {d: set(g) for d, g in DIMENSION_GUARD.items()}
    # in_scope is protected by the three out-of-scope refusal categories
    return mapping


def render(report: dict) -> str:
    lines = [
        "# Conversation eval",
        "",
        f"- conversations: {report['conversations']}  turns: {report['turns']}"
        + (f" (stratified subset of {report['turns_available']}, seed {report['subset_seed']})"
           if report.get("subset") else ""),
        "- source: patients loaded in FHIR; the medications named are theirs",
        f"- judge: none. Every dimension is scored deterministically against the expected",
        "  outcome recorded with the turn.",
        f"- run date: {report['run_date']}",
        "",
        "## Rubric",
        "",
        "Turns tagged `hard_*` are paraphrases that carry no phrase from the guardrail's",
        "tables. They are included on purpose: without them this table reads 100% across",
        "the board, which would only be measuring that the generator and the matcher share",
        "a trigger list. The gap below is the honest ceiling of a keyword guardrail.",
        "",
        "| Dimension | Passed | Total | Rate | 95% CI |",
        "|---|---:|---:|---:|---|",
    ]
    for dimension, entry in report["rubric"].items():
        lo, hi = entry["ci"]
        lines.append(
            f"| `{dimension}` | {entry['passed']} | {entry['total']} | "
            f"{entry['rate'] * 100:.1f}% | [{lo * 100:.1f}, {hi * 100:.1f}] |"
        )
    lines += ["", "## Per-guard mutation", "",
              "Each row removes one guard and re-runs the whole set. The dimension that guard",
              "protects must get worse, or the guard is not doing the work the rubric credits.",
              "", "| Guard removed | Dimension | Before | After | Dropped |",
              "|---|---|---:|---:|:--:|"]
    for guard, rows in report["mutation"].items():
        for row in rows:
            lines.append(
                f"| `{guard}` | `{row['dimension']}` | {row['before'] * 100:.1f}% | "
                f"{row['after'] * 100:.1f}% | {'yes' if row['dropped'] else 'NO'} |"
            )
    if report.get("subset"):
        lines += ["", "### Subset composition", "",
                  "| Turn kind | Turns evaluated |", "|---|---:|"]
        lines += [f"| `{k}` | {v} |" for k, v in sorted(report["subset_strata"].items())]
        lines += ["",
                  "A flat random sample would leave some guards with nothing to bite on. Every",
                  "kind above is represented, so a small-budget run still exercises all of them."]
    lines += ["", "## Latency (harness only, scripted drafts)", "",
              f"- p50 {report['latency_ms']['p50']:.2f} ms, p95 {report['latency_ms']['p95']:.2f} ms,"
              f" p99 {report['latency_ms']['p99']:.2f} ms"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from clinical_agent.telemetry import percentile
    from datetime import date

    parser = argparse.ArgumentParser(prog="eval.conversation_run")
    parser.add_argument("--conversations", type=Path, default=ROOT / "data" / "conversations.json")
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--turns-subset", type=int, default=0,
                        help="evaluate about N turns, stratified across guard categories. "
                             "0 (default) runs the whole set.")
    parser.add_argument("--subset-seed", type=int, default=20260904)
    args = parser.parse_args(argv)

    conversations = load(args.conversations)
    available = sum(len(c["turns"]) for c in conversations)
    strata: dict[str, int] = {}
    if args.turns_subset:
        conversations, strata = stratified_subset(
            conversations, args.turns_subset, args.subset_seed)
    corpus = Corpus.load(ROOT / "data" / "corpus")

    scores, latencies = run_set(conversations, corpus)
    rubric = aggregate(scores)
    for dimension, entry in rubric.items():
        entry["ci"] = wilson(entry["passed"], entry["total"])

    report = {
        "conversations": len(conversations),
        "turns": len(scores),
        "turns_available": available,
        "subset": bool(strata),
        "subset_seed": args.subset_seed if strata else None,
        "subset_strata": strata or None,
        "run_date": date.today().isoformat(),
        "rubric": rubric,
        "mutation": mutation_matrix(conversations, corpus, rubric),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "conversation-eval.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "conversation-eval.md").write_text(render(report), encoding="utf-8")
    print(render(report))

    failed = [
        f"{guard} -> {row['dimension']}"
        for guard, rows in report["mutation"].items()
        for row in rows
        if not row["dropped"]
    ]
    if failed:
        print("MUTATION FAILURES: " + "; ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
