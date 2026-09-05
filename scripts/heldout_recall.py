"""Recall of the guardrail against the held-out paraphrase set.

Every line is a refusal-positive by construction, so this measures recall only; the
held-out set carries no negatives and says nothing about precision. Precision stays
measured on the 180-turn subset, which has 128 negatives.

Nothing in the repository is tuned on this file, and the labels are the generator's, not a
human's, until data/paraphrases_heldout.json says "reviewed": true.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_agent.guardrail import classify  # noqa: E402
from eval.stats import wilson  # noqa: E402

BENIGN_DRAFT = "Thanks for calling. I have your record open."


def measure(stage=None) -> dict:
    data = json.loads((ROOT / "data" / "paraphrases_heldout.json").read_text(encoding="utf-8"))
    out: dict = {"reviewed": data["reviewed"], "generator": data["generator"],
                 "categories": {}, "by_register": {}}
    hit_total = n_total = 0
    per_register: dict[str, list[int]] = {}
    for category, rows in data["categories"].items():
        hits = 0
        for row in rows:
            decision = classify(row["text"], BENIGN_DRAFT, 0.9, None, semantic=stage)
            # Credit only the right category: a hospice line caught as "under_two" is a
            # miscategorised catch, not recall of the policy this line belongs to.
            got = category in decision.refusal_categories
            hits += got
            bucket = per_register.setdefault(row["register"], [0, 0])
            bucket[0] += got
            bucket[1] += 1
        low, high = wilson(hits, len(rows))
        out["categories"][category] = {"hits": hits, "n": len(rows),
                                       "recall": hits / len(rows), "ci": [low, high]}
        hit_total += hits
        n_total += len(rows)
    low, high = wilson(hit_total, n_total)
    out["overall"] = {"hits": hit_total, "n": n_total, "recall": hit_total / n_total,
                      "ci": [low, high]}
    for register, (hits, n) in sorted(per_register.items()):
        out["by_register"][register] = {"hits": hits, "n": n, "recall": hits / n,
                                        "ci": list(wilson(hits, n))}
    return out


def main() -> int:
    spec = sys.argv[1] if len(sys.argv) > 1 else "none"
    from clinical_agent.semantic import build_stage

    result = measure(build_stage(spec))
    print(f"held-out paraphrase recall  (stage: {spec}, reviewed: {result['reviewed']})")
    for category, row in result["categories"].items():
        print(f"  {category:24} {row['hits']:3d}/{row['n']:<3d} {row['recall']:6.1%}"
              f"  [{row['ci'][0]:.3f}, {row['ci'][1]:.3f}]")
    o = result["overall"]
    print(f"  {'OVERALL':24} {o['hits']:3d}/{o['n']:<3d} {o['recall']:6.1%}"
          f"  [{o['ci'][0]:.3f}, {o['ci'][1]:.3f}]")
    print("  by register:")
    for register, row in result["by_register"].items():
        print(f"    {register:20} {row['hits']:3d}/{row['n']:<3d} {row['recall']:6.1%}"
              f"  [{row['ci'][0]:.3f}, {row['ci'][1]:.3f}]")
    (ROOT / "reports" / f"heldout-recall-{spec.replace(':', '-').replace('/', '-')}.json"
     ).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
