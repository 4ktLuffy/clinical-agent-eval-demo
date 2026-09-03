"""Replay gate. Runs the full conversation set and blocks a deploy on regression.

This is the check the runbook calls before traffic. It compares the current run against a
committed baseline and fails if any rubric dimension has fallen by more than the tolerance,
or if any per-guard mutation has stopped biting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from clinical_agent.rag import Corpus
from eval.conversation_run import ROOT, load, mutation_matrix, run_set
from eval.rubric import aggregate

BASELINE = ROOT / "reports" / "replay-baseline.json"
TOLERANCE = 0.01  # a dimension may not fall more than one point below baseline


def current(conversations_path: Path) -> dict:
    conversations = load(conversations_path)
    corpus = Corpus.load(ROOT / "data" / "corpus")
    scores, _ = run_set(conversations, corpus)
    rubric = aggregate(scores)
    return {
        "turns": len(scores),
        "rubric": {d: e["rate"] for d, e in rubric.items()},
        "mutation_all_drop": all(
            row["dropped"]
            for rows in mutation_matrix(conversations, corpus, rubric).values()
            for row in rows
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.replay")
    parser.add_argument("--conversations", type=Path, default=ROOT / "data" / "conversations.json")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = parser.parse_args(argv)

    key_present = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    print(f"replay: {'real-model judge available' if key_present else 'mock path only, no API key present'}")

    now = current(args.conversations)

    if args.update_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written to {args.baseline} ({now['turns']} turns)")
        return 0

    if not args.baseline.exists():
        print(f"no baseline at {args.baseline}; run with --update-baseline first", file=sys.stderr)
        return 1

    before = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = []
    print(f"{'dimension':<28} {'baseline':>9} {'now':>9} {'delta':>8}")
    for dimension, baseline_rate in before["rubric"].items():
        now_rate = now["rubric"].get(dimension, 0.0)
        delta = now_rate - baseline_rate
        flag = ""
        if delta < -args.tolerance:
            failures.append(f"{dimension} fell {abs(delta) * 100:.1f} points")
            flag = "  REGRESSION"
        print(f"{dimension:<28} {baseline_rate * 100:>8.1f}% {now_rate * 100:>8.1f}% {delta * 100:>+7.1f}{flag}")

    if not now["mutation_all_drop"]:
        failures.append("a per-guard mutation stopped biting")

    if failures:
        print("\nREPLAY GATE FAILED — deploy blocked: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("\nreplay gate passed: no regression beyond tolerance, every guard still bites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
