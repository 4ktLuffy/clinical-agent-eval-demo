"""Derive the retrieval threshold for an embedding backend.

The rule, fixed before any measurement: the MiniLM threshold is the quantile of MiniLM
top-1 scores that keeps the SAME fraction of in-repo turns above threshold as the hashed
backend's 0.18 keeps. Matching the rate is what makes the two backends comparable -- any
change in citation precision is then caused by *which* chunks come back, not by one
backend simply retrieving more often than the other.

Only the in-repo 180-turn subset is used. No held-out set is read here, and none may be:
a threshold fitted to held-out data would make every held-out number self-referential.

Usage: python scripts/retrieval_threshold.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def top_scores(backend: str) -> list[float]:
    os.environ["CLINICAL_EMBEDDINGS"] = backend
    for module in [m for m in list(sys.modules) if m.startswith("clinical_agent")]:
        del sys.modules[module]
    from clinical_agent.rag import Corpus  # noqa: PLC0415

    from eval.conversation_run import stratified_subset  # noqa: PLC0415

    corpus = Corpus.load(ROOT / "data" / "corpus")
    conversations = json.loads((ROOT / "data" / "conversations.json").read_text())
    subset, _ = stratified_subset(conversations, 180, 20260904)
    scores = []
    for conversation in subset:
        for turn in conversation["turns"]:
            hits = corpus.retrieve(turn["text"], k=4)
            scores.append(hits[0].score if hits else 0.0)
    return scores


def main() -> int:
    hashed = top_scores("hashed")
    kept = sum(1 for s in hashed if s >= 0.18)
    rate = kept / len(hashed)
    print(f"hashed  threshold 0.18 keeps {kept}/{len(hashed)} turns ({rate:.1%})")

    minilm = sorted(top_scores("minilm"), reverse=True)
    index = min(kept, len(minilm)) - 1
    matched = minilm[index] if index >= 0 else 0.0
    # The exact quantile score, to 6dp. Rounding it in either direction breaks the rate
    # match: down admits everything in between (57% became 78%), up excludes a whole tie
    # block (57% became 44%), because the 180-turn subset holds only 23 distinct texts and
    # their scores tie heavily. Ties mean the rate cannot land exactly on the hashed rate;
    # the check below allows five points of slack and prints what was actually achieved.
    import math

    # Floor, not round: rounding to 6dp landed a hair ABOVE the true quantile and excluded
    # the entire tie block sitting on it, which dropped the kept rate from 57% to 44%.
    threshold = math.floor(matched * 1_000_000) / 1_000_000
    now = sum(1 for s in minilm if s >= threshold)
    print(f"minilm  matching quantile {matched:.4f} -> threshold {threshold:.6f} "
          f"keeps {now}/{len(minilm)} ({now / len(minilm):.1%})")

    from clinical_agent.rag import _RETRIEVAL_THRESHOLDS  # noqa: PLC0415

    configured = _RETRIEVAL_THRESHOLDS["minilm"]
    print(f"configured minilm threshold: {configured:.6f}")
    if abs(configured - threshold) > 1e-6:
        print("STALE: the configured minilm threshold no longer matches the rule")
        return 1
    if abs(now / len(minilm) - rate) > 0.05:
        print(f"STALE: minilm keeps {now / len(minilm):.1%} against hashed {rate:.1%}; "
              "the backends are no longer rate-matched and their citation numbers are "
              "not comparable")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
