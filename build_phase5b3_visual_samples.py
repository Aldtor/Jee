"""Build visual audit sheets for source-confirmed Phase 5B.3 promotions."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
JM = ROOT / "JEE_QUESTION_DATABASE_FINAL" / "JEE_MAIN"
BATCH_DIR = ROOT / "audit" / "ocr_review_batches"
OUT = ROOT / "audit" / "ocr_review_batches" / "visual_samples"
MAX_PER_YEAR = 30
CARD_W, CARD_H = 480, 360
COLS = 5
ROWS = 6


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def choose(records: list[dict]) -> list[dict]:
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_bucket[str(row.get("primary_bucket") or "low_ocr_confidence")].append(row)
    selected: list[dict] = []
    # Round-robin buckets first so the visual audit covers all promotion paths.
    buckets = sorted(by_bucket)
    index = 0
    while len(selected) < min(MAX_PER_YEAR, len(records)) and buckets:
        bucket = buckets[index % len(buckets)]
        if by_bucket[bucket]:
            selected.append(by_bucket[bucket].pop(0))
        else:
            buckets.remove(bucket)
            index -= 1
        index += 1
    return selected


def main() -> None:
    image_rows = {row.get("image_id"): row for row in read_jsonl(JM / "images.jsonl")}
    promoted: list[dict] = []
    for path in sorted(BATCH_DIR.glob("batch_*_records.jsonl")):
        for row in read_jsonl(path):
            if row.get("content_status") == "CONTENT_VERIFIED":
                promoted.append(row)
    by_year: dict[str, list[dict]] = defaultdict(list)
    for row in promoted:
        by_year[str(row.get("year"))].append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, list[dict]] = {}
    font = ImageFont.load_default()
    for year in sorted(by_year):
        selected = choose(sorted(by_year[year], key=lambda r: (str(r.get("primary_bucket")), str(r.get("occurrence_id")))) )
        manifest[year] = []
        sheets: list[Image.Image] = []
        for offset in range(0, len(selected), COLS * ROWS):
            chunk = selected[offset : offset + COLS * ROWS]
            sheet = Image.new("RGB", (COLS * CARD_W, ROWS * CARD_H), "white")
            draw = ImageDraw.Draw(sheet)
            for pos, row in enumerate(chunk):
                image_row = next((image_rows.get(image_id) for image_id in row.get("source_image_ids", []) if image_rows.get(image_id, {}).get("image_type") == "question_crop"), None)
                if not image_row:
                    continue
                source = ROOT / image_row["image_path"]
                try:
                    with Image.open(source) as loaded:
                        image = loaded.convert("RGB")
                        image.thumbnail((CARD_W - 12, CARD_H - 58), Image.Resampling.LANCZOS)
                        x = (pos % COLS) * CARD_W + (CARD_W - image.width) // 2
                        y = (pos // COLS) * CARD_H + 34
                        sheet.paste(image, (x, y))
                except Exception:
                    continue
                label = f"{row.get('occurrence_id')} | {row.get('subject')} | {row.get('primary_bucket')}"
                draw.text(((pos % COLS) * CARD_W + 6, (pos // COLS) * CARD_H + 6), label[:74], fill="black", font=font)
                manifest[year].append({"occurrence_id": row.get("occurrence_id"), "bucket": row.get("primary_bucket"), "image_path": image_row["image_path"]})
            sheet_path = OUT / f"promoted_visual_audit_{year}_{offset // (COLS * ROWS) + 1:02d}.png"
            sheet.save(sheet_path, optimize=True)
            sheets.append(sheet)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"promoted": len(promoted), "years": {year: len(rows) for year, rows in manifest.items()}, "output": str(OUT)}))


if __name__ == "__main__":
    main()
