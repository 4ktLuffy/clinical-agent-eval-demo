"""Interactive reviewer for held-out v2 and the open-ended label sheet.

One item at a time, no back-scrolling, single-key answers, saved after every one.

Two things about the design are deliberate and load-bearing:

  The guardrail's verdict is never shown. If the screen said "the table caught this one",
  the review would drift towards agreeing with the thing it exists to check, and the
  held-out numbers would quietly become a measure of how persuasive the tool was.

  It never writes to data/paraphrases_heldout_v2.json. Answers go to a gitignored progress
  file and then to an annotations file; `scripts/apply_review.py` is the only thing that
  edits the set, because that script is idempotent, logged, and tested. A reviewer's
  session should not be able to corrupt a measured set by being interrupted.

Usage:
  python scripts/review.py                 # resume, or start
  python scripts/review.py --status        # how far through, no prompts
  python scripts/review.py --paraphrases   # just one of the two
  python scripts/review.py --labels
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "data" / "paraphrases_heldout_v2.json"
LABELS = ROOT / "data" / "labels_open_ended.csv"
PROGRESS = ROOT / "data" / "review-progress.json"
ANNOTATIONS = ROOT / "data" / "review-annotations.json"

SCORE_KEYS = {"0": 0.0, "5": 0.5, "1": 1.0}


def _wrap(text: str, indent: str = "    ") -> str:
    import textwrap

    width = max(40, min(shutil.get_terminal_size((100, 24)).columns, 100) - len(indent))
    return "\n".join(indent + line for line in textwrap.wrap(text, width)) or indent


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {"started": date.today().isoformat(), "paraphrases": {}, "labels": {}}


def save(progress: dict) -> None:
    """Written after every single answer. A reviewer who stops mid-way, or whose terminal
    dies, loses nothing."""
    PROGRESS.write_text(json.dumps(progress, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def paraphrase_items() -> list[dict]:
    """Positives first, then negatives, in file order."""
    data = json.loads(V2.read_text(encoding="utf-8"))
    items = []
    for half in ("categories", "negatives"):
        for category, rows in data[half].items():
            for index, entry in enumerate(rows):
                items.append({"key": f"{half}/{category}/{index}", "half": half,
                              "category": category, "text": entry["text"]})
    return items


def ask(prompt: str, allowed: set[str]) -> str:
    while True:
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            print("\n  input ended; progress is saved, run again to resume")
            raise SystemExit(0)
        if answer in allowed:
            return answer
        print(f"    expected one of {sorted(allowed)}")


def review_paraphrases(progress: dict) -> bool:
    items = paraphrase_items()
    done = progress["paraphrases"]
    remaining = [i for i in items if i["key"] not in done]
    if not remaining:
        return True
    print(f"\n=== paraphrases: {len(done)} of {len(items)} done, {len(remaining)} to go ===")
    print("  k keep    s strike (then a two-word reason)    r relabel (then a category)")
    print("  q quit — progress is saved after every answer\n")
    categories = sorted(json.loads(V2.read_text(encoding="utf-8"))["categories"])
    for number, item in enumerate(remaining, 1):
        half = "POSITIVE — should this be refused?" if item["half"] == "categories" \
            else "NEGATIVE — would refusing this be wrong?"
        print(f"[{len(done) + 1}/{len(items)}]  {item['category']}   {half}")
        print(_wrap(item["text"]))
        answer = ask("  k / s / r / q > ", {"k", "s", "r", "q"})
        if answer == "q":
            print("  stopped. Run again to resume here.")
            return False
        record: dict = {"action": {"k": "keep", "s": "strike", "r": "relabel"}[answer],
                        "text": item["text"], "category": item["category"],
                        "half": item["half"]}
        if answer == "s":
            while True:
                reason = input("  two-word reason > ").strip().lower()
                if len(reason.split()) == 2:
                    record["reason"] = reason
                    break
                print("    exactly two words, per data/LABELLING.md")
        if answer == "r":
            print(f"    categories: {', '.join(categories)}")
            while True:
                target = input("  relabel to > ").strip().lower()
                if target in categories:
                    record["to"] = target
                    break
                print(f"    expected one of {categories}")
        done[item["key"]] = record
        save(progress)
        print()
    return True


def label_rows() -> list[dict]:
    lines = [ln for ln in LABELS.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def review_labels(progress: dict) -> bool:
    rows = label_rows()
    done = progress["labels"]
    remaining = [r for r in rows if r["turn_id"] not in done]
    if not remaining:
        return True
    print(f"\n=== open-ended turns: {len(done)} of {len(rows)} done ===")
    print("  0 = 0.0    5 = 0.5    1 = 1.0    q quit\n")
    for row in remaining:
        print(f"[{len(done) + 1}/{len(rows)}]  {row['turn_id']}")
        print("  DRAFT")
        print(_wrap(row.get("draft_excerpt", "")))
        print("  CITED")
        for chunk in (row.get("cited_chunks") or "").split(" || "):
            if chunk.strip():
                print(_wrap(chunk.strip(), indent="      "))
        faith = ask("  faithfulness  0 / 5 / 1 / q > ", {"0", "5", "1", "q"})
        if faith == "q":
            print("  stopped. Run again to resume here.")
            return False
        cite = ask("  citation      0 / 5 / 1 / q > ", {"0", "5", "1", "q"})
        if cite == "q":
            print("  stopped. Run again to resume here.")
            return False
        done[row["turn_id"]] = {"faithfulness": SCORE_KEYS[faith],
                                "citation_quality": SCORE_KEYS[cite]}
        save(progress)
        print()
    return True


def write_annotations(progress: dict) -> int:
    """The strike/relabel lines, in the shape apply_review.py reads. v2 is not touched."""
    out = {}
    for record in progress["paraphrases"].values():
        if record["action"] == "strike":
            out[record["text"]] = f"strike: {record['reason']}"
        elif record["action"] == "relabel":
            out[record["text"]] = f"relabel: {record['to']}"
    ANNOTATIONS.write_text(json.dumps(
        {"_note": "Written by scripts/review.py. Apply with "
                  "`python scripts/apply_review.py --annotations data/review-annotations.json`.",
         "reviewed_on": date.today().isoformat(),
         "annotations": out}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(out)


def write_labels(progress: dict) -> int:
    """Fills the two score columns in place, preserving the comments, the header and every
    other column exactly as `--labels` expects to read them."""
    text = LABELS.read_text(encoding="utf-8")
    comments = [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]
    rows = label_rows()
    filled = 0
    for row in rows:
        answer = progress["labels"].get(row["turn_id"])
        if answer:
            row["faithfulness"] = str(answer["faithfulness"])
            row["citation_quality"] = str(answer["citation_quality"])
            filled += 1
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    LABELS.write_text("\n".join(comments) + "\n" + buffer.getvalue(), encoding="utf-8")
    return filled


def status(progress: dict) -> None:
    items, rows = paraphrase_items(), label_rows()
    p, l = len(progress["paraphrases"]), len(progress["labels"])
    print(f"paraphrases  {p}/{len(items)}")
    print(f"open-ended   {l}/{len(rows)}")
    if p == len(items) and l == len(rows):
        print("both complete — annotations and the filled CSV have been written")
    from collections import Counter

    actions = Counter(r["action"] for r in progress["paraphrases"].values())
    if actions:
        print("so far: " + ", ".join(f"{k} {v}" for k, v in sorted(actions.items())))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--paraphrases", action="store_true")
    parser.add_argument("--labels", action="store_true")
    args = parser.parse_args(argv)

    progress = load_progress()
    if args.status:
        status(progress)
        return 0

    both = not (args.paraphrases or args.labels)
    finished = True
    if args.paraphrases or both:
        finished &= review_paraphrases(progress)
    if finished and (args.labels or both):
        finished &= review_labels(progress)

    save(progress)
    wrote_annotations = write_annotations(progress)
    wrote_labels = write_labels(progress)
    print(f"\nsaved: {len(progress['paraphrases'])} paraphrase verdicts "
          f"({wrote_annotations} strike/relabel), {wrote_labels} label rows filled")

    items, rows = paraphrase_items(), label_rows()
    if len(progress["paraphrases"]) == len(items) and len(progress["labels"]) == len(rows):
        print("\nBoth complete. Next:")
        print("  python scripts/apply_review.py --annotations data/review-annotations.json")
        print("  python scripts/heldout_recall.py local")
        print("  make readme-check number-audit")
    else:
        print("Run again to resume where you stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
