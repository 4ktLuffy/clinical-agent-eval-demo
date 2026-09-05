"""Recompute the derived columns in reports-sweep/handread.json from the sweep rows.

The hand-read verdicts are human judgements and are preserved untouched. Everything that
can be derived -- empty-draft counts, scored denominators, rates and intervals -- is
recomputed here, because a resumed sweep segment changes the denominators and a stale
derived number is exactly the kind of thing this repository keeps finding.

`hand_read_through_turn` records how far the verdicts actually reach. When a resume adds
turns, the verdicts do not automatically cover them and the file says so.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SWEEP = ROOT / "reports-sweep"

from eval.stats import wilson  # noqa: E402

SKIP = {"excluded.json", "handread.json", "latency-rules.json", "progress.json"}


def main() -> int:
    hand = json.loads((SWEEP / "handread.json").read_text(encoding="utf-8"))
    for path in sorted(SWEEP.glob("*.json")):
        if path.name in SKIP:
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        model = run["model"]
        row = hand.setdefault(model, {})
        rows = run["rows"]
        empty = [r for r in rows if not (r["draft"] or "").strip()]
        scored = len(rows) - len(empty)
        flagged = [r for r in rows if r["draft_categories"]]

        row["flagged_raw"] = len(flagged)
        row["empty_drafts"] = len(empty)
        row["scored_turns"] = scored
        row["turns"] = len(rows)
        row.setdefault("hand_read_through_turn", len(rows))
        verdict_rate = row.get("verified_rate")
        if verdict_rate is not None:
            # Verified count scales with the flagged drafts the verdicts actually cover.
            covered = min(row["hand_read_through_turn"], len(rows))
            flagged_covered = sum(1 for r in rows[:covered] if r["draft_categories"])
            real = flagged_covered * verdict_rate
            row["verified_out_of_scope_estimate"] = round(real, 1)
            row["verified_flagged_covered"] = flagged_covered
            low, high = wilson(round(real), max(scored, 1))
            row["verified_rate_per_scored_turn"] = round(real / scored, 4) if scored else None
            row["verified_ci_scored"] = [round(low, 3), round(high, 3)]
        if row.get("unflagged_scored"):
            low, high = wilson(row["unflagged_missed"], row["unflagged_scored"])
            row["miss_rate"] = round(row["unflagged_missed"] / row["unflagged_scored"], 3)
            row["miss_rate_ci"] = [round(low, 3), round(high, 3)]
        row["verdicts_cover_whole_run"] = row["hand_read_through_turn"] >= len(rows)

    (SWEEP / "handread.json").write_text(json.dumps(hand, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    print(f"{'model':30}{'turns':>6}{'empty':>6}{'scored':>7}{'flagged':>8}{'covered':>8}")
    for model, row in sorted(hand.items()):
        print(f"{model:30}{row['turns']:6d}{row['empty_drafts']:6d}{row['scored_turns']:7d}"
              f"{row['flagged_raw']:8d}{'yes' if row['verdicts_cover_whole_run'] else 'NO':>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
