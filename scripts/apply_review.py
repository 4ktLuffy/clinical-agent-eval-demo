"""Apply a human review to the held-out set.

The reviewer annotates lines in place, per data/LABELLING.md:

    "strike: not asking"        drop the line from its denominator
    "relabel: hospice"          move the line to another category

This script reads those annotations, applies them, and records what it did. Three
properties matter more than the code:

  idempotent   running it twice changes nothing the second time. A review that drifts
               each time it is applied is not a review.
  additive     a struck line is marked, never deleted. The counts stay checkable against
               the file a reviewer actually read.
  logged       every change is written to data/review-log.json with the reason, so a
               figure can be traced back to the annotation that moved it.

It refuses to run against a set with no annotations, rather than silently reporting a
clean review of nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELD_OUT = ROOT / "data" / "paraphrases_heldout_v2.json"
LOG = ROOT / "data" / "review-log.json"

STRIKE = "strike:"
RELABEL = "relabel:"


def parse(entry: dict) -> tuple[str | None, str | None]:
    """Returns (struck_reason, relabel_target) from whatever the reviewer wrote."""
    note = " ".join(str(entry.get(key, "")) for key in ("note", "review", "annotation"))
    struck = target = None
    for token in note.replace(",", " ").split(STRIKE)[1:]:
        struck = " ".join(token.split()[:2]) or "unspecified"
        break
    for token in note.split(RELABEL)[1:]:
        target = token.split()[0].strip() if token.split() else None
        break
    return struck, target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=HELD_OUT)
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--annotations", type=Path, default=None,
                        help="JSON written by scripts/review.py: {text: 'strike: two words'}. "
                             "The reviewer never edits the held-out set itself, so this is "
                             "how its verdicts reach it -- through the one script that is "
                             "idempotent, logged and tested.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    data = json.loads(args.path.read_text(encoding="utf-8"))

    if args.annotations:
        external = json.loads(args.annotations.read_text(encoding="utf-8"))
        notes = external.get("annotations", external)
        attached = 0
        for half in ("categories", "negatives"):
            for rows in data[half].values():
                for entry in rows:
                    note = notes.get(entry["text"])
                    if note and entry.get("note") != note:
                        entry["note"] = note
                        attached += 1
        print(f"attached {attached} annotation(s) from {args.annotations.name}")
    changes: list[dict] = []
    already = 0

    for half in ("categories", "negatives"):
        for category, rows in list(data[half].items()):
            # Iterate a copy: a relabel removes from `rows`, and mutating a list while
            # walking it skips the element after every removal -- two adjacent relabels
            # would silently leave the second one unapplied.
            for entry in list(rows):
                struck, target = parse(entry)
                if not struck and not target:
                    continue
                if entry.get("struck") or entry.get("relabelled_from"):
                    already += 1
                    continue
                if struck:
                    entry["struck"] = struck
                    changes.append({"half": half, "category": category,
                                    "text": entry["text"][:80], "action": "strike",
                                    "reason": struck})
                if target and target != category:
                    if target not in data[half]:
                        print(f"  refusing to relabel into unknown category {target!r}",
                              file=sys.stderr)
                        return 2
                    entry["relabelled_from"] = category
                    data[half][target].append(entry)
                    rows.remove(entry)
                    changes.append({"half": half, "category": category,
                                    "text": entry["text"][:80], "action": "relabel",
                                    "to": target})

    if not changes and not already:
        print("no strike or relabel annotations found; nothing to apply. Add them per "
              "data/LABELLING.md before running this.", file=sys.stderr)
        return 3

    counts: dict[str, dict[str, int]] = {}
    for half in ("categories", "negatives"):
        for category, rows in data[half].items():
            counts.setdefault(half, {})[category] = sum(1 for r in rows if r.get("struck"))

    data["reviewed"] = True
    data["strikes_per_category"] = counts

    if args.dry_run:
        print(f"dry run: {len(changes)} change(s), {already} already applied")
        return 0

    args.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    history = json.loads(args.log.read_text(encoding="utf-8")) if args.log.exists() else []
    history.append({"applied_on": date.today().isoformat(), "changes": changes,
                    "already_applied": already, "strikes_per_category": counts})
    args.log.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"applied {len(changes)} change(s), {already} already applied; "
          f"reviewed=true, strike counts written to {args.log.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
