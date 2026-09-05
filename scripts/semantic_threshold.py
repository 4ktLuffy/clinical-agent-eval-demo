"""Regenerate the local semantic stage's threshold from the negatives.

The rule, fixed before any refusal-positive turn was inspected: the threshold is the
smallest round value strictly above the highest score any refusal-NEGATIVE turn reaches.
Run this after changing data/semantic_exemplars.json -- if the printed floor rises above
the configured threshold, the stage now has false positives and the threshold is stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.semantic import LocalSemanticStage, default_threshold  # noqa: E402
from eval.conversation_run import stratified_subset  # noqa: E402


def main() -> int:
    import os

    from clinical_agent.embeddings import backend as _b
    from clinical_agent.semantic import exemplar_set as _e
    print(f"backend: {_b()}  exemplars: {_e()}")
    configured = default_threshold()
    stage = LocalSemanticStage()
    conversations = json.loads((ROOT / "data" / "conversations.json").read_text())
    subset, _ = stratified_subset(conversations, 180, 20260904)
    worst, worst_turn = 0.0, ""
    positives = 0
    for conversation in subset:
        for turn in conversation["turns"]:
            expect = turn["expect"]
            refusal_positive = (expect["out_of_scope"] or expect["asks_diagnosis"]
                                or expect["asks_prescription"])
            top = max(stage.scores(turn["text"]).values())
            if refusal_positive:
                positives += top >= configured
            elif top > worst:
                worst, worst_turn = top, turn["text"]
    print(f"highest refusal-negative score: {worst:.3f}  ({worst_turn[:60]})")
    print(f"configured threshold:           {configured:.3f}")
    print(f"refusal-positive turns at or above threshold: {positives}")
    import math

    implied = math.floor(worst / 0.05) * 0.05 + 0.05
    print(f"rule (smallest multiple of 0.05 above the floor): {implied:.2f}")
    if abs(implied - configured) > 0.001:
        print("STALE: the configured threshold is not what the rule gives")
        return 1
    if configured <= worst:
        print("STALE: threshold is at or below the negative floor; it now fires on "
              "turns that must not be refused")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
