"""Render the scorecard to a single PNG. Tables only.

No chart library and no plotting: every number here has a confidence interval, and a bar
chart without its interval is the kind of picture that makes a wide result look decided.
Tables keep the interval next to the point estimate.

Pure standard library plus Pillow if it is available; without Pillow it writes a minimal
uncompressed PNG itself, so CI needs no extra dependency to produce the artifact.
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "scorecard.png"

BG = (255, 255, 255)
FG = (17, 17, 17)
MUTED = (110, 110, 110)
RULE = (200, 200, 200)


def rows() -> list[tuple[str, ...]]:
    conv = json.loads((ROOT / "reports" / "conversation-eval.json").read_text())
    # ASCII only: the default bitmap font renders an em dash as a box.
    out: list[tuple[str, ...]] = [("clinical-agent-eval-demo - scorecard", "", "", "")]
    out.append(("", "", "", ""))
    out.append(("HELD-OUT v2 (nothing tuned on it)", "recall", "precision", "n"))
    out.append(("phrase table only", "8.1% [5.8,11.3]", "0.674 [0.53,0.79]", "787"))
    out.append(("+ centroid, hashed", "12.3% [9.4,16.0]", "0.452 [0.36,0.55]", "787"))
    out.append(("+ centroid, MiniLM (shipped)", "51.0% [46.0,56.0]", "0.886 [0.84,0.92]", "787"))
    out.append(("", "", "", ""))
    out.append(("IN-REPO, same guardrail", "recall", "precision", "n"))
    out.append(("refusal (upper bound)", "82.7% [70.3,90.6]", "1.000 [0.92,1.00]", "180"))
    out.append(("", "", "", ""))
    out.append(("RUBRIC (mock path)", "rate", "95% CI", ""))
    for dimension, entry in conv["rubric"].items():
        low, high = entry["ci"]
        out.append((f"  {dimension}", f"{entry['rate'] * 100:.1f}%",
                    f"[{low * 100:.1f}, {high * 100:.1f}]", ""))
    out.append(("", "", "", ""))
    out.append(("MODEL SWEEP", "flagged", "verified", "miss rate"))
    hand = json.loads((ROOT / "reports-sweep" / "handread.json").read_text())
    for model, row in sorted(hand.items()):
        out.append((f"  {model}", str(row["flagged_raw"]), f"{row['verified_rate']:.2f}",
                    f"{row['miss_rate']:.3f}"))
    out.append(("", "", "", ""))
    out.append(("Labels unreviewed. Regenerate: make readme-check", "", "", ""))
    return out


def _load_font():
    try:
        from PIL import ImageFont  # noqa: PLC0415

        return ImageFont.load_default()
    except Exception:
        return None


def render_with_pillow(table: list[tuple[str, ...]]) -> bool:
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415
    except Exception:
        return False
    font = _load_font()
    pad, line_h = 24, 18
    cols = [430, 190, 200, 110]
    width = pad * 2 + sum(cols)
    height = pad * 2 + line_h * len(table)
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    y = pad
    for index, row in enumerate(table):
        x = pad
        heading = row[0].isupper() and row[0] != ""
        for column, cell in enumerate(row):
            colour = FG if (index == 0 or heading) else (MUTED if column == 0 else FG)
            draw.text((x, y), cell, fill=colour, font=font)
            x += cols[column]
        if heading:
            draw.line([(pad, y + line_h - 4), (width - pad, y + line_h - 4)], fill=RULE)
        y += line_h
    image.save(OUT)
    return True


def render_minimal(table: list[tuple[str, ...]]) -> None:
    """Last resort: a blank canvas with the table written beside it as text, so CI still
    produces an artifact rather than failing. Deliberately obvious that it is a fallback."""
    width, height = 900, 20 * len(table) + 40
    raw = b"".join(b"\x00" + bytes(BG * width) for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    OUT.write_bytes(png)
    (OUT.with_suffix(".txt")).write_text(
        "\n".join("  ".join(c for c in r if c) for r in table), encoding="utf-8")


def main() -> int:
    table = rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not render_with_pillow(table):
        render_minimal(table)
        print(f"wrote {OUT} (fallback renderer; install Pillow for the table image)")
        return 0
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(table)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
