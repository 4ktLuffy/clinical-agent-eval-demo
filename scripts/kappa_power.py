"""How large would n have to be for the kappa interval to clear zero?

Holds the observed agreement pattern fixed and replicates it, which answers: if the judge
keeps behaving exactly as it did on these turns, how many turns are needed before the 95%
bootstrap interval excludes chance? It is a floor, not a forecast -- real extra turns bring
variety this replication cannot, so treat the answer as the most optimistic n.

Usage: python scripts/kappa_power.py reports-judge-120b/scorecard.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eval.stats import cohens_kappa, kappa_interval  # noqa: E402

MAX_MULTIPLIER = 60


def needed(judge: list, label: list, axis: str) -> None:
    point = cohens_kappa(judge, label)
    n = len(judge)
    for k in range(1, MAX_MULTIPLIER + 1):
        lo, hi = kappa_interval(judge * k, label * k)
        if lo > 0:
            print(f"{axis:16} kappa {point:+.3f}  n={n} -> needs n>={n * k} "
                  f"({k}x) for 95% CI [{lo:+.3f}, {hi:+.3f}] to clear zero")
            return
    print(f"{axis:16} kappa {point:+.3f}  n={n} -> not cleared by n={n * MAX_MULTIPLIER}")


def main(path: str) -> int:
    cal = json.loads(Path(path).read_text(encoding="utf-8"))["calibration"]
    rows = cal["per_turn"]
    print(f"{cal['judge']}  n={cal['n']}")
    needed([r["judge_faithfulness_bucketed"] for r in rows],
           [r["label_faithfulness"] for r in rows], "faithfulness")
    needed([r["judge_citation_bucketed"] for r in rows],
           [r["label_citation"] for r in rows], "citation_quality")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
