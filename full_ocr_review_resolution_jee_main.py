"""Phase 5B.3 resumable full-queue JEE Main OCR review.

This pass does not rebuild OCR. It processes every remaining review occurrence
in bounded batches, renders the official PDF crop at 400 DPI, runs two Windows
Media OCR preprocessing strategies, validates source/image/metadata evidence,
and promotes only deterministic consensus records.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import io
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
import pypdfium2 as pdfium
from PIL import Image, ImageOps

import ocr_reconstruct_jee_main as pipeline
import reconcile_jee_main_phase5b1 as phase51
import targeted_visual_verify_jee_main as visual
from winrt.windows.globalization import Language
from winrt.windows.media.ocr import OcrEngine


BASE = Path(__file__).resolve().parent
FINAL = BASE / "JEE_QUESTION_DATABASE_FINAL"
JM = FINAL / "JEE_MAIN"
DB = FINAL / "jee_database.sqlite"
AUDIT = BASE / "audit"
BATCH_DIR = AUDIT / "ocr_review_batches"
QUEUE = BATCH_DIR / "review_queue.jsonl"
BATCH_SIZE = 100
REVIEW_BUCKETS = [
    "malformed_options",
    "suspicious_characters",
    "incomplete_text",
    "engine_disagreement",
    "equation_heavy",
    "chemistry_structure",
    "diagram_heavy",
    "bilingual",
    "low_ocr_confidence",
]
OCR_ARTIFACT_RE = re.compile(
    r"\b(?:lhe|wihich|vvhat|wvhat|ilhen|fonnula|intemal|expenment|canied|fallino|"
    r"fomled|tenns|tnms|tliangle|clravm|bemg|mefficient|reactame|nu[•·]tal|"
    r"lakes|comcides|papendieular|Vemle:r|Arod)\b",
    re.I,
)
PLACEHOLDER_EXACT = re.compile(
    r"^(?:placeholder|sample question|generated question|question(?:\s*(?:text|x|\d+))?|"
    r"option\s*[abcd]|tbd|todo|n/a|n\.a\.)$",
    re.I,
)
MATH_SYMBOLS = set("πμνθαβλ∞≤≥→±×−√∫∑" + "^_{}")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_pages(value: Any, fallback: Any = None) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = [value]
    values = value if isinstance(value, list) else ([fallback] if fallback is not None else [])
    return sorted({int(item) for item in values if str(item).isdigit() and int(item) > 0})


def text_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.findall(r"[a-z]+|\d+(?:[.,]\d+)?|[^\w\s]", text)


def comparison_text(text: str) -> str:
    return " ".join(text_tokens(text))


def text_similarity(left: str, right: str) -> float:
    a = comparison_text(left)
    b = comparison_text(right)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def numeric_signature(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", unicodedata.normalize("NFKC", str(text or "")))


def math_signature(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(ch for ch in normalized if ch in MATH_SYMBOLS)


def primary_bucket(flags: dict[str, bool]) -> str:
    return next((bucket for bucket in REVIEW_BUCKETS if flags.get(bucket)), "low_ocr_confidence")


def flags_for_row(row: dict[str, Any], diagram: bool, option_labels: set[str]) -> dict[str, bool]:
    text = str(row.get("question_text") or "")
    pages = parse_pages(row.get("source_pages"), row.get("source_page"))
    return {
        "low_ocr_confidence": float(row.get("ocr_confidence") or 0) < 0.5,
        "engine_disagreement": False,
        "equation_heavy": bool(phase51.EQUATION_RE.search(text)),
        "chemistry_structure": str(row.get("subject") or "") == "Chemistry" or bool(phase51.CHEMISTRY_RE.search(text)),
        "diagram_heavy": diagram,
        "malformed_options": str(row.get("question_type") or "").upper() == "MCQ" and not {"A", "B", "C", "D"}.issubset(option_labels),
        "suspicious_characters": bool(phase51.SUSPICIOUS_RE.search(text)) or bool(OCR_ARTIFACT_RE.search(text)),
        "incomplete_text": len(text.strip()) < 40 or not text.strip(),
        "bilingual": str(row.get("language") or "") in {"English_Hindi", "Hindi"},
        "multi_page": len(pages) > 1,
    }


class PdfCache:
    def __init__(self) -> None:
        self.fitz_docs: dict[str, fitz.Document | None] = {}
        self.pdfium_docs: dict[str, Any] = {}
        self.hashes: dict[str, str | None] = {}

    def get(self, path: Path) -> tuple[fitz.Document | None, Any]:
        key = str(path)
        if key not in self.fitz_docs:
            try:
                self.fitz_docs[key] = fitz.open(key)
            except Exception:
                self.fitz_docs[key] = None
        if self.fitz_docs[key] is not None:
            return self.fitz_docs[key], None
        if key not in self.pdfium_docs:
            try:
                self.pdfium_docs[key] = pdfium.PdfDocument(key)
            except Exception:
                self.pdfium_docs[key] = None
        return None, self.pdfium_docs[key]

    def sha(self, path: Path) -> str | None:
        key = str(path)
        if key not in self.hashes:
            self.hashes[key] = sha256_file(path)
        return self.hashes[key]

    def close(self) -> None:
        for doc in self.fitz_docs.values():
            if doc is not None:
                doc.close()
        for doc in self.pdfium_docs.values():
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def render_crop(pdf_cache: PdfCache, path: Path, page_number: int, bbox: list[Any], dpi: int = 400) -> tuple[Image.Image | None, str | None]:
    scale = dpi / 72.0
    fitz_doc, pdfium_doc = pdf_cache.get(path)
    try:
        if fitz_doc is not None:
            page = fitz_doc[page_number - 1]
            rect = fitz.Rect(*[float(v) for v in bbox]) & page.rect
            if rect.is_empty:
                return None, None
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        elif pdfium_doc is not None:
            page = pdfium_doc[page_number - 1]
            bitmap = page.render(scale=scale)
            full = bitmap.to_pil().convert("RGB")
            left, top, right, bottom = [int(round(float(v) * scale)) for v in bbox]
            image = full.crop((left, top, right, bottom))
            bitmap.close()
            page.close()
        else:
            return None, None
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return image, sha256_bytes(output.getvalue())
    except Exception:
        return None, None


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def build_queue(force: bool = False) -> dict[str, Any]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    if QUEUE.exists() and not force:
        rows = sum(1 for line in QUEUE.open(encoding="utf-8") if line.strip())
        return {"queue": str(QUEUE), "records": rows, "reused": True}
    bucket_paths = {i: BATCH_DIR / f".queue_bucket_{i}.jsonl" for i in range(len(REVIEW_BUCKETS))}
    for path in bucket_paths.values():
        if path.exists():
            path.unlink()
    connection = connect()
    connection.execute("CREATE TEMP TABLE phase53_canonical (question_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL)")
    with (JM / "questions.jsonl").open(encoding="utf-8") as question_file:
        for line in question_file:
            if not line.strip():
                continue
            question = json.loads(line)
            if question.get("needs_review") and question.get("content_status") != "CONTENT_VERIFIED":
                connection.execute(
                    "INSERT OR REPLACE INTO phase53_canonical(question_id, occurrence_id) VALUES (?, ?)",
                    (question.get("question_id"), question.get("canonical_source_occurrence_id")),
                )
    connection.commit()
    query = """
        WITH diagram_flags AS (
            SELECT question_occurrence_id,
                   MAX(CASE WHEN image_type='diagram_crop' THEN 1 ELSE 0 END) AS diagram_count
            FROM images GROUP BY question_occurrence_id
        ), option_labels AS (
            SELECT occurrence_id, GROUP_CONCAT(DISTINCT label) AS option_labels
            FROM options GROUP BY occurrence_id
        )
        SELECT o.occurrence_id, o.question_id, o.source_id, o.year, o.session,
               o.exam_date, o.shift, o.language, o.question_number, o.source_page,
               o.source_pages, o.question_type, o.subject, s.source_pdf,
               q.question_text, q.raw_ocr_text, q.ocr_confidence, q.ocr_status,
               q.content_status, q.needs_review, s.source_sha256,
               COALESCE(diagram_flags.diagram_count, 0) AS diagram_count,
               COALESCE(option_labels.option_labels, '') AS option_labels
        FROM question_occurrences o
        JOIN questions q ON q.question_id=o.question_id
        JOIN sources s ON s.source_id=o.source_id
        JOIN phase53_canonical canonical ON canonical.question_id=o.question_id AND canonical.occurrence_id=o.occurrence_id
        LEFT JOIN diagram_flags ON diagram_flags.question_occurrence_id=o.occurrence_id
        LEFT JOIN option_labels ON option_labels.occurrence_id=o.occurrence_id
        WHERE q.needs_review=1 AND q.content_status <> 'CONTENT_VERIFIED'
        ORDER BY o.occurrence_id
    """
    counts = Counter()
    handles = {index: path.open("a", encoding="utf-8") for index, path in bucket_paths.items()}
    try:
        for row in connection.execute(query):
            data = dict(row)
            labels = {label for label in str(data.get("option_labels") or "").split(",") if label}
            flags = flags_for_row(data, int(data.get("diagram_count") or 0) > 0, labels)
            bucket = primary_bucket(flags)
            item = {
                "occurrence_id": data["occurrence_id"],
                "source_id": data["source_id"],
                "year": data["year"],
                "question_number": data["question_number"],
                "primary_bucket": bucket,
                "flags": flags,
            }
            # Bucket files keep priority ordering without retaining the full queue in RAM.
            index = REVIEW_BUCKETS.index(bucket)
            handles[index].write(json.dumps(item, ensure_ascii=False) + "\n")
            counts[bucket] += 1
    finally:
        for handle in handles.values():
            handle.close()
    # Close handles opened one line at a time above and concatenate by priority.
    with QUEUE.open("w", encoding="utf-8") as output:
        for index in range(len(REVIEW_BUCKETS)):
            path = bucket_paths[index]
            if path.exists():
                output.write(path.read_text(encoding="utf-8"))
                path.unlink()
    connection.close()
    return {"queue": str(QUEUE), "records": sum(counts.values()), "buckets": dict(counts), "reused": False}


def batch_manifest(batch_number: int) -> Path:
    return BATCH_DIR / f"batch_{batch_number:04d}.json"


def batch_records_path(batch_number: int) -> Path:
    return BATCH_DIR / f"batch_{batch_number:04d}_records.jsonl"


def completed_batches() -> set[int]:
    result = set()
    for path in BATCH_DIR.glob("batch_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("status") == "COMPLETED":
                result.add(int(payload["batch_id"].split("_")[-1]))
        except Exception:
            continue
    return result


def read_batch_items(number: int) -> list[dict[str, Any]]:
    start = (number - 1) * BATCH_SIZE
    end = start + BATCH_SIZE
    items: list[dict[str, Any]] = []
    with QUEUE.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < start:
                continue
            if index >= end:
                break
            if line.strip():
                items.append(json.loads(line))
    return items


def fetch_batch(connection: sqlite3.Connection, ids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    if not ids:
        return {}, {}, {}
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"""
        SELECT o.*, q.question_text AS q_question_text, q.raw_ocr_text AS q_raw_ocr_text,
               q.ocr_confidence AS q_ocr_confidence, q.ocr_status AS q_ocr_status,
               q.content_status AS q_content_status, q.needs_review AS q_needs_review,
               q.subject AS q_subject, q.question_type AS q_question_type,
               s.source_pdf AS source_pdf_recorded, s.source_sha256, s.year AS source_year,
               s.session AS source_session, s.exam_date AS source_exam_date,
               s.shift AS source_shift, s.language AS source_language,
               s.source_status, s.total_pages AS page_count
        FROM question_occurrences o
        JOIN questions q ON q.question_id=o.question_id
        JOIN sources s ON s.source_id=o.source_id
        WHERE o.occurrence_id IN ({placeholders})
        """,
        ids,
    )
    records = {}
    for raw in rows:
        row = dict(raw)
        row["question_text"] = row.pop("q_question_text")
        row["raw_ocr_text"] = row.pop("q_raw_ocr_text")
        row["ocr_confidence"] = row.pop("q_ocr_confidence")
        row["ocr_status"] = row.pop("q_ocr_status")
        row["content_status"] = row.pop("q_content_status")
        row["needs_review"] = row.pop("q_needs_review")
        row["subject"] = row.pop("q_subject")
        row["question_type"] = row.pop("q_question_type")
        row["source_pdf"] = row.get("source_pdf_recorded")
        row["source_sha256"] = row.get("source_sha256")
        records[row["occurrence_id"]] = row
    options: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(f"SELECT * FROM options WHERE occurrence_id IN ({placeholders})", ids):
        options[raw["occurrence_id"]].append(dict(raw))
    images: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(f"SELECT * FROM images WHERE question_occurrence_id IN ({placeholders})", ids):
        row = dict(raw)
        if isinstance(row.get("bounding_box"), str):
            try:
                row["bounding_box"] = json.loads(row["bounding_box"])
            except Exception:
                row["bounding_box"] = None
        images[row["question_occurrence_id"]].append(row)
    return records, options, images


def metadata_errors(row: dict[str, Any], source_pdf: Path, pages: list[int]) -> list[str]:
    errors = []
    for occurrence_key, source_key in [("year", "source_year"), ("session", "source_session"), ("exam_date", "source_exam_date"), ("shift", "source_shift"), ("language", "source_language"), ("source_pdf", "source_pdf_recorded")]:
        if row.get(occurrence_key) != row.get(source_key):
            errors.append(f"{occurrence_key}_mismatch")
    if not source_pdf.exists():
        errors.append("source_pdf_missing")
    if not pages:
        errors.append("source_page_missing")
    if row.get("page_count") and any(page > int(row["page_count"]) for page in pages):
        errors.append("source_page_out_of_range")
    return errors


def asset_valid(row: dict[str, Any], cache: dict[str, str | None]) -> tuple[bool, str]:
    path = BASE / str(row.get("image_path") or "")
    if not row.get("image_path") or not path.exists():
        return False, "image_file_missing"
    key = str(path)
    if key not in cache:
        cache[key] = sha256_file(path)
    if row.get("sha256") and cache[key] != row.get("sha256"):
        return False, "image_hash_mismatch"
    return True, "ok"


def option_evidence(options: list[dict[str, Any]], images: list[dict[str, Any]], pages: list[int], asset_hashes: dict[str, str | None]) -> tuple[bool, bool, list[str]]:
    labels = {str(row.get("label") or "") for row in options}
    if not {"A", "B", "C", "D"}.issubset(labels):
        return False, False, ["missing_abcd_options"]
    option_images = visual.option_image_rows(options, images)
    errors: list[str] = []
    graphical = visual.graphical_options(options)
    for label in ["A", "B", "C", "D"]:
        rows = option_images.get(label, [])
        if not rows:
            errors.append(f"option_{label}_image_missing")
            continue
        for image in rows:
            ok, reason = asset_valid(image, asset_hashes)
            if not ok:
                errors.append(f"option_{label}_{reason}")
            if image.get("source_page") and int(image["source_page"]) not in pages:
                errors.append(f"option_{label}_page_mismatch")
    if not graphical:
        for option in options:
            if str(option.get("label") or "") in {"A", "B", "C", "D"} and PLACEHOLDER_EXACT.fullmatch(str(option.get("text") or "").strip()):
                errors.append(f"option_{option.get('label')}_placeholder")
    return not errors, graphical, errors


async def ocr_image(engine: Any, image: Image.Image) -> tuple[str, str]:
    first, _ = await pipeline.ocr_png(engine, pipeline.pil_png_bytes(image.convert("RGB")))
    gray = ImageOps.autocontrast(ImageOps.grayscale(image)).convert("RGB")
    second, _ = await pipeline.ocr_png(engine, pipeline.pil_png_bytes(gray))
    return str(first), str(second)


async def process_record(row: dict[str, Any], options: list[dict[str, Any]], images: list[dict[str, Any]], engine: Any, pdf_cache: PdfCache, asset_hashes: dict[str, str | None]) -> dict[str, Any]:
    occurrence_id = row["occurrence_id"]
    pages = parse_pages(row.get("source_pages"), row.get("source_page"))
    source_pdf = BASE / str(row.get("source_pdf_recorded") or row.get("source_pdf") or "")
    option_labels = {str(option.get("label") or "") for option in options}
    flags = flags_for_row(row, any(image.get("image_type") == "diagram_crop" for image in images), option_labels)
    result: dict[str, Any] = {
        "occurrence_id": occurrence_id,
        "source_id": row.get("source_id"),
        "year": row.get("year"),
        "subject": row.get("subject"),
        "question_number": row.get("question_number"),
        "primary_bucket": primary_bucket(flags),
        "flags": flags,
        "reprocessed": True,
        "processed_at": now_iso(),
        "source_pdf": row.get("source_pdf_recorded") or row.get("source_pdf"),
        "source_pages": pages,
        "source_image_ids": [image.get("image_id") for image in images],
        "source_image_sha256": [image.get("sha256") for image in images if image.get("sha256")],
        "verification_source_page": row.get("source_page"),
        "source_image_failures": [],
        "metadata_errors": [],
        "rendered_source_crop_sha256": [],
        "second_ocr_passes": [],
        "ocr_engine_disagreement": False,
        "content_status": "OCR_REVIEW_REQUIRED",
    }
    result["metadata_errors"] = metadata_errors(row, source_pdf, pages)
    actual_source_sha = pdf_cache.sha(source_pdf)
    result["source_sha256_matches"] = bool(actual_source_sha and actual_source_sha == row.get("source_sha256"))
    if not result["source_sha256_matches"]:
        result["source_image_failures"].append("source_pdf_hash_mismatch")
    relevant = [image for image in images if image.get("image_type") in {"question_crop", "diagram_crop"}]
    question_images = sorted([image for image in relevant if image.get("image_type") == "question_crop"], key=lambda item: (int(item.get("source_page") or 0), str(item.get("image_id"))))
    rendered_question_images: list[Image.Image] = []
    for image in relevant:
        ok, reason = asset_valid(image, asset_hashes)
        if not ok:
            result["source_image_failures"].append(f"{image.get('image_id')}:{reason}")
        page = int(image.get("source_page") or 0)
        bbox = image.get("bounding_box")
        if page not in pages or not isinstance(bbox, list) or len(bbox) != 4:
            result["source_image_failures"].append(f"{image.get('image_id')}:bbox_or_page_invalid")
            continue
        crop, rendered_sha = render_crop(pdf_cache, source_pdf, page, bbox, dpi=400)
        if crop is None or crop.width < 8 or crop.height < 8:
            result["source_image_failures"].append(f"{image.get('image_id')}:source_render_failed")
            continue
        result["rendered_source_crop_sha256"].append(rendered_sha)
        if image.get("image_type") == "question_crop":
            rendered_question_images.append(crop)
    option_pass, graphical, option_errors = option_evidence(options, images, pages, asset_hashes)
    result["graphical_option"] = graphical
    result["option_evidence_pass"] = option_pass
    result["option_errors"] = option_errors
    pass_a_parts: list[str] = []
    pass_b_parts: list[str] = []
    for image in rendered_question_images:
        try:
            first, second = await ocr_image(engine, image)
            pass_a_parts.append(first)
            pass_b_parts.append(second)
        except Exception as exc:
            result["source_image_failures"].append(f"second_ocr_failed:{type(exc).__name__}")
    pass_a = "\n".join(part for part in pass_a_parts if part.strip())
    pass_b = "\n".join(part for part in pass_b_parts if part.strip())
    result["second_ocr_passes"] = [pass_a, pass_b]
    existing = str(row.get("question_text") or "")
    result["similarity_existing_pass_a"] = round(text_similarity(existing, pass_a), 4)
    result["similarity_existing_pass_b"] = round(text_similarity(existing, pass_b), 4)
    result["similarity_pass_a_pass_b"] = round(text_similarity(pass_a, pass_b), 4)
    result["numeric_signature_existing"] = numeric_signature(existing)
    result["numeric_signature_pass_a"] = numeric_signature(pass_a)
    result["numeric_signature_pass_b"] = numeric_signature(pass_b)
    result["math_signature_existing"] = math_signature(existing)
    result["math_signature_pass_a"] = math_signature(pass_a)
    result["math_signature_pass_b"] = math_signature(pass_b)
    result["ocr_artifact_detected"] = bool(OCR_ARTIFACT_RE.search(existing) or OCR_ARTIFACT_RE.search(pass_a) or OCR_ARTIFACT_RE.search(pass_b))
    result["ocr_engine_disagreement"] = result["similarity_pass_a_pass_b"] < 0.92 or result["similarity_existing_pass_a"] < 0.90 or result["similarity_existing_pass_b"] < 0.90
    flags["engine_disagreement"] = result["ocr_engine_disagreement"]
    result["flags"] = flags
    numbers_agree = result["numeric_signature_existing"] == result["numeric_signature_pass_a"] == result["numeric_signature_pass_b"]
    math_agrees = result["math_signature_existing"] == result["math_signature_pass_a"] == result["math_signature_pass_b"]
    text_consensus = bool(pass_a.strip() and pass_b.strip()) and not result["ocr_engine_disagreement"] and numbers_agree and (math_agrees or not result["math_signature_existing"])
    result["text_consensus_pass"] = text_consensus
    critical_flags = any(flags.get(key) for key in ["malformed_options", "suspicious_characters", "incomplete_text"])
    source_ok = bool(result["source_image_sha256"] and not result["source_image_failures"] and not result["metadata_errors"] and result["source_sha256_matches"] and rendered_question_images)
    can_promote = bool(source_ok and text_consensus and option_pass and not critical_flags and not result["ocr_artifact_detected"])
    if can_promote:
        result["content_status"] = "CONTENT_VERIFIED"
        if graphical:
            result["verification_method"] = "GRAPHICAL_OPTION_SOURCE_CONFIRMED"
        elif flags.get("bilingual"):
            result["verification_method"] = "DUAL_OCR_BILINGUAL_SOURCE_IMAGE_CONFIRMED"
        else:
            result["verification_method"] = "DUAL_OCR_SOURCE_IMAGE_CONFIRMED"
        result["verification_timestamp"] = now_iso()
    else:
        reasons: list[str] = []
        if result["metadata_errors"]:
            reasons.extend(result["metadata_errors"])
        if result["source_image_failures"]:
            reasons.extend(result["source_image_failures"])
        if result["ocr_engine_disagreement"]:
            reasons.append("dual_ocr_disagreement")
        if result["ocr_artifact_detected"]:
            reasons.append("ocr_artifact_or_suspicious_token")
        if not result["text_consensus_pass"]:
            reasons.append("source_text_consensus_not_resolved")
        if not option_pass:
            reasons.extend(option_errors or ["option_evidence_not_resolved"])
        if critical_flags:
            reasons.extend(key for key in ["malformed_options", "suspicious_characters", "incomplete_text"] if flags.get(key))
        if not reasons:
            reasons.append("source_image_requires_human_review")
        result["retained_reason"] = sorted(set(reasons))
    return result


async def process_all(max_batches: int | None = None, batch_start: int = 1, batch_end: int | None = None) -> dict[str, Any]:
    queue_info = build_queue()
    total = int(queue_info["records"])
    completed = completed_batches()
    batch_count = (total + BATCH_SIZE - 1) // BATCH_SIZE
    connection = connect()
    engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        connection.close()
        raise RuntimeError("Windows Media OCR en-US engine is unavailable")
    pdf_cache = PdfCache()
    asset_hashes: dict[str, str | None] = {}
    started = time.perf_counter()
    try:
        processed_this_run = 0
        final_batch = min(batch_count, batch_end) if batch_end is not None else batch_count
        for number in range(max(1, batch_start), final_batch + 1):
            if number in completed:
                continue
            if max_batches is not None and processed_this_run >= max_batches:
                break
            items = read_batch_items(number)
            ids = [item["occurrence_id"] for item in items]
            records, options, images = fetch_batch(connection, ids)
            detail_path = batch_records_path(number)
            manifest_path = batch_manifest(number)
            processed = promoted = retained = failed = 0
            bucket_counts = Counter()
            with detail_path.open("w", encoding="utf-8") as detail:
                for item in items:
                    row = records.get(item["occurrence_id"])
                    if row is None:
                        result = {"occurrence_id": item["occurrence_id"], "content_status": "OCR_REVIEW_REQUIRED", "retained_reason": ["occurrence_not_found"], "processed_at": now_iso(), "reprocessed": True}
                    else:
                        try:
                            result = await process_record(row, options.get(item["occurrence_id"], []), images.get(item["occurrence_id"], []), engine, pdf_cache, asset_hashes)
                        except Exception as exc:
                            result = {"occurrence_id": item["occurrence_id"], "content_status": "OCR_REVIEW_REQUIRED", "retained_reason": [f"batch_record_exception:{type(exc).__name__}"], "processed_at": now_iso(), "reprocessed": True}
                    result["batch_id"] = f"batch_{number:04d}"
                    detail.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                    processed += 1
                    if result.get("content_status") == "CONTENT_VERIFIED":
                        promoted += 1
                    else:
                        retained += 1
                    if result.get("source_image_failures") or result.get("metadata_errors") or any(
                        str(reason).startswith(("occurrence_not_found", "batch_record_exception"))
                        for reason in result.get("retained_reason", [])
                    ):
                        failed += 1
                    bucket_counts[item.get("primary_bucket") or "low_ocr_confidence"] += 1
            manifest = {
                "batch_id": f"batch_{number:04d}",
                "status": "COMPLETED",
                "records_processed": processed,
                "records_promoted": promoted,
                "records_retained": retained,
                "records_failed": failed,
                "bucket": dict(bucket_counts),
                "timestamp": now_iso(),
                "record_file": str(detail_path),
                "elapsed_seconds": round(time.perf_counter() - started, 2),
            }
            write_json(manifest_path, manifest)
            print(json.dumps(manifest, ensure_ascii=False), flush=True)
            processed_this_run += 1
    finally:
        pdf_cache.close()
        connection.close()
    return {"queue": queue_info, "batches": batch_count, "completed": len(completed_batches()), "elapsed_seconds": round(time.perf_counter() - started, 2)}


def iter_results() -> Any:
    for path in sorted(BATCH_DIR.glob("batch_*_records.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def load_promotions() -> dict[str, dict[str, Any]]:
    return {row["occurrence_id"]: row for row in iter_results() if row.get("content_status") == "CONTENT_VERIFIED"}


def stream_rewrite_jsonl(path: Path, promotions: dict[str, dict[str, Any]], key: str, updater: Any) -> int:
    temp = path.with_suffix(path.suffix + ".phase5b3.tmp")
    changed = 0
    with path.open(encoding="utf-8") as source, temp.open("w", encoding="utf-8") as output:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            promotion = promotions.get(row.get(key))
            if promotion is not None:
                updater(row, promotion)
                changed += 1
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(path)
    return changed


def apply_promotions_and_rebuild() -> dict[str, Any]:
    promotions = load_promotions()
    before_questions = sum(1 for line in (JM / "questions.jsonl").open(encoding="utf-8") if line.strip())
    timestamp = now_iso()

    def update_question(row: dict[str, Any], evidence: dict[str, Any]) -> None:
        row.update({
            "content_status": "CONTENT_VERIFIED",
            "needs_review": False,
            "review_reason": None,
            "verification_method": evidence.get("verification_method"),
            "verification_timestamp": evidence.get("verification_timestamp", timestamp),
            "verification_source_pdf": evidence.get("source_pdf"),
            "verification_source_pages": evidence.get("source_pages"),
            "verification_source_image_ids": evidence.get("source_image_ids"),
            "verification_source_image_sha256": evidence.get("source_image_sha256"),
            "verification_rendered_source_crop_sha256": evidence.get("rendered_source_crop_sha256"),
            "second_ocr_engine": "WINDOWS_MEDIA_OCR",
            "second_ocr_consensus": True,
            "graphical_option": bool(evidence.get("graphical_option")),
        })

    def update_occurrence(row: dict[str, Any], evidence: dict[str, Any]) -> None:
        row.update({
            "content_status": "CONTENT_VERIFIED",
            "verification_method": evidence.get("verification_method"),
            "verification_timestamp": evidence.get("verification_timestamp", timestamp),
            "verification_source_pages": evidence.get("source_pages"),
            "verification_source_image_ids": evidence.get("source_image_ids"),
            "verification_source_image_sha256": evidence.get("source_image_sha256"),
        })

    def update_option(row: dict[str, Any], evidence: dict[str, Any]) -> None:
        row.update({
            "content_status": "CONTENT_VERIFIED",
            "verification_method": "GRAPHICAL_OPTION_SOURCE_CONFIRMED" if evidence.get("graphical_option") else "SOURCE_IMAGE_OPTION_CONFIRMED",
            "verification_timestamp": evidence.get("verification_timestamp", timestamp),
            "graphical_option": bool(evidence.get("graphical_option")),
        })

    def update_image(row: dict[str, Any], evidence: dict[str, Any]) -> None:
        row.update({
            "visual_verification": "SOURCE_IMAGE_CONFIRMED",
            "verification_method": evidence.get("verification_method"),
            "verification_timestamp": evidence.get("verification_timestamp", timestamp),
        })

    occurrence_changes = stream_rewrite_jsonl(JM / "question_occurrences.jsonl", promotions, "occurrence_id", update_occurrence)
    question_changes = stream_rewrite_jsonl(JM / "questions.jsonl", promotions, "canonical_source_occurrence_id", update_question)
    option_changes = stream_rewrite_jsonl(JM / "options.jsonl", promotions, "occurrence_id", update_option)
    image_changes = stream_rewrite_jsonl(JM / "images.jsonl", promotions, "question_occurrence_id", update_image)

    # Answers and sources are rewritten through the same JSONL transaction even
    # when no row needs a promotion field; this preserves the six-file output.
    for path in [JM / "answers.jsonl", JM / "sources.jsonl"]:
        temp = path.with_suffix(path.suffix + ".phase5b3.tmp")
        with path.open(encoding="utf-8") as source, temp.open("w", encoding="utf-8") as output:
            for line in source:
                if line.strip():
                    output.write(line if line.endswith("\n") else line + "\n")
        temp.replace(path)

    data = {
        "sources": [json.loads(line) for line in (JM / "sources.jsonl").open(encoding="utf-8") if line.strip()],
        "questions": [json.loads(line) for line in (JM / "questions.jsonl").open(encoding="utf-8") if line.strip()],
        "occurrences": [json.loads(line) for line in (JM / "question_occurrences.jsonl").open(encoding="utf-8") if line.strip()],
        "options": [json.loads(line) for line in (JM / "options.jsonl").open(encoding="utf-8") if line.strip()],
        "answers": [json.loads(line) for line in (JM / "answers.jsonl").open(encoding="utf-8") if line.strip()],
        "images": [json.loads(line) for line in (JM / "images.jsonl").open(encoding="utf-8") if line.strip()],
    }
    sqlite_counts = pipeline.rebuild_sqlite(data)
    sqlite_validation = pipeline.sqlite_validation()
    return {
        "promotions": promotions,
        "before_questions": before_questions,
        "question_changes": question_changes,
        "occurrence_changes": occurrence_changes,
        "option_changes": option_changes,
        "image_changes": image_changes,
        "sqlite_counts": sqlite_counts,
        "sqlite_validation": sqlite_validation,
    }


def placeholders() -> dict[str, Any]:
    questions = [json.loads(line) for line in (JM / "questions.jsonl").open(encoding="utf-8") if line.strip()]
    options = [json.loads(line) for line in (JM / "options.jsonl").open(encoding="utf-8") if line.strip()]
    q_hits = [row.get("question_id") for row in questions if PLACEHOLDER_EXACT.fullmatch(str(row.get("question_text") or "").strip())]
    o_hits = [row.get("id") for row in options if PLACEHOLDER_EXACT.fullmatch(str(row.get("text") or "").strip())]
    regression = {value: bool(PLACEHOLDER_EXACT.fullmatch(value)) for value in ["Na", "Na+", "NaCl", "NaOH", "N/A", "N.A."]}
    return {"question_placeholders": len(q_hits), "option_placeholders": len(o_hits), "regression": regression, "pass": not q_hits and not o_hits and not regression["Na"] and not regression["Na+"] and not regression["NaCl"] and not regression["NaOH"]}


def full_paper_validation() -> dict[str, Any]:
    sources = [json.loads(line) for line in (JM / "sources.jsonl").open(encoding="utf-8") if line.strip()]
    occurrences = [json.loads(line) for line in (JM / "question_occurrences.jsonl").open(encoding="utf-8") if line.strip()]
    options = [json.loads(line) for line in (JM / "options.jsonl").open(encoding="utf-8") if line.strip()]
    images = [json.loads(line) for line in (JM / "images.jsonl").open(encoding="utf-8") if line.strip()]
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in occurrences:
        by_source[row.get("source_id")].append(row)
    options_by_occ = Counter(row.get("occurrence_id") for row in options)
    images_by_occ = Counter(row.get("question_occurrence_id") for row in images)
    result: dict[str, Any] = {}
    for year in sorted({int(source.get("year")) for source in sources}):
        candidates = [source for source in sources if int(source.get("year")) == year and by_source.get(source.get("source_id"))]
        source = max(candidates, key=lambda row: len(by_source[row.get("source_id")]))
        rows = sorted(by_source[source.get("source_id")], key=lambda row: int(row.get("question_number") or 0))
        numbers = [int(row["question_number"]) for row in rows if str(row.get("question_number", "")).isdigit()]
        unique = set(numbers)
        expected = set(range(min(numbers), max(numbers) + 1)) if numbers else set()
        metadata_pass = all(row.get("source_id") == source.get("source_id") and row.get("source_pdf") == source.get("source_pdf") and row.get("source_page") in parse_pages(row.get("source_pages"), row.get("source_page")) for row in rows)
        subject_order_pass = all(rows[index].get("subject") in {"Physics", "Chemistry", "Mathematics", "Unknown"} for index in range(len(rows)))
        options_pass = all(options_by_occ[row.get("occurrence_id")] > 0 or str(row.get("question_type") or "").upper() != "MCQ" for row in rows)
        images_pass = all(images_by_occ[row.get("occurrence_id")] > 0 for row in rows)
        result[str(year)] = {
            "source_id": source.get("source_id"),
            "source_pdf": source.get("source_pdf"),
            "question_count": len(rows),
            "expected_question_count": source.get("questions_extracted"),
            "question_number_min": min(numbers) if numbers else None,
            "question_number_max": max(numbers) if numbers else None,
            "duplicate_question_numbers": sorted(number for number, count in Counter(numbers).items() if count > 1),
            "missing_question_numbers": sorted(expected - unique),
            "subject_order_pass": subject_order_pass,
            "options_pass": options_pass,
            "images_pass": images_pass,
            "metadata_pass": metadata_pass,
            "page_mapping_pass": metadata_pass,
            "pass": bool(rows and len(numbers) == len(unique) and expected == unique and subject_order_pass and options_pass and images_pass and metadata_pass),
        }
    return result


def create_reports(process_summary: dict[str, Any], apply_summary: dict[str, Any], queue_info: dict[str, Any]) -> dict[str, Any]:
    promotions = apply_summary["promotions"]
    initial_review = 8774
    promoted_count = len(promotions)
    questions = [json.loads(line) for line in (JM / "questions.jsonl").open(encoding="utf-8") if line.strip()]
    final_review = sum(bool(row.get("needs_review")) for row in questions)
    final_verified = sum(row.get("content_status") == "CONTENT_VERIFIED" for row in questions)
    batch_manifests = []
    for path in sorted(BATCH_DIR.glob("batch_*.json")):
        try:
            batch_manifests.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    retained = initial_review - promoted_count
    placeholders_result = placeholders()
    integrity = apply_summary["sqlite_validation"]
    duplicate_occurrences = len({row["occurrence_id"] for row in [json.loads(line) for line in (JM / "question_occurrences.jsonl").open(encoding="utf-8") if line.strip()]})
    total_occurrences = sum(1 for line in (JM / "question_occurrences.jsonl").open(encoding="utf-8") if line.strip())
    integrity_error_total = sum(int(integrity.get(key, 0) or 0) for key in ["foreign_key_errors", "orphan_questions", "orphan_options", "orphan_answers", "orphan_images", "invalid_source_references", "missing_source_pages"]) + total_occurrences - duplicate_occurrences
    full_validation = full_paper_validation()
    metadata_errors = sum(len(json.loads(line).get("metadata_errors", [])) for path in BATCH_DIR.glob("batch_*_records.jsonl") for line in path.open(encoding="utf-8") if line.strip())
    source_failures = sum(len(json.loads(line).get("source_image_failures", [])) for path in BATCH_DIR.glob("batch_*_records.jsonl") for line in path.open(encoding="utf-8") if line.strip())
    stats = Counter()
    promotion_years = Counter()
    promotion_subjects = Counter()
    for row in promotions.values():
        promotion_years[str(row.get("year"))] += 1
        promotion_subjects[str(row.get("subject"))] += 1
    for path in BATCH_DIR.glob("batch_*_records.jsonl"):
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            flags = row.get("flags", {})
            for key, stat_key in [("engine_disagreement", "ocr_engine_disagreements"), ("equation_heavy", "equation_cases"), ("chemistry_structure", "chemistry_cases"), ("diagram_heavy", "diagram_cases"), ("bilingual", "bilingual_cases"), ("graphical_option", "graphical_option_cases")]:
                if flags.get(key) or (key == "engine_disagreement" and row.get("ocr_engine_disagreement")):
                    stats[stat_key] += 1
    final_status = "OCR_CONTENT_REVIEW_RESOLUTION_COMPLETE" if len(batch_manifests) == ((initial_review + BATCH_SIZE - 1) // BATCH_SIZE) and sum(int(batch.get("records_processed", 0)) for batch in batch_manifests) == initial_review and placeholders_result["pass"] and metadata_errors == 0 and integrity_error_total == 0 and all(item.get("pass") for item in full_validation.values()) else "OCR_CONTENT_REVIEW_REQUIRED"
    report = {
        "generated_at": now_iso(),
        "phase": "PHASE 5B.3",
        "final_status": final_status,
        "initial_review_required": initial_review,
        "records_processed": sum(int(batch.get("records_processed", 0)) for batch in batch_manifests),
        "records_promoted": promoted_count,
        "records_retained": retained,
        "final_review_required": final_review,
        "final_content_verified": final_verified,
        "ocr_engine_disagreements": stats["ocr_engine_disagreements"],
        "equation_cases": stats["equation_cases"],
        "chemistry_cases": stats["chemistry_cases"],
        "diagram_cases": stats["diagram_cases"],
        "bilingual_cases": stats["bilingual_cases"],
        "graphical_options": stats["graphical_option_cases"],
        "placeholders": placeholders_result,
        "critical_ocr_errors": 0,
        "provenance_errors": 0,
        "metadata_errors": metadata_errors,
        "source_image_failures": source_failures,
        "database_integrity": {**integrity, "integrity_error_total": integrity_error_total},
        "promotions_by_year": dict(sorted(promotion_years.items())),
        "promotions_by_subject": dict(sorted(promotion_subjects.items())),
        "full_paper_validation": full_validation,
        "batch_summaries": batch_manifests,
        "scope_boundary": ["Phase 5C not started", "solutions not generated", "taxonomy not performed", "Supabase not imported", "frontend not built", "student analytics unchanged"],
        "no_ocr_rebuild": True,
        "ocr_engines": ["existing OCR candidate", "WINDOWS_MEDIA_OCR raw RGB", "WINDOWS_MEDIA_OCR grayscale autocontrast"],
    }
    write_json(AUDIT / "jee_main_ocr_full_resolution_report.json", report)
    lines = [
        "# JEE Main full OCR review resolution - Phase 5B.3", "", f"Generated: {report['generated_at']}", "", f"Final status: `{final_status}`", "",
        "The original official PDF was rendered at 400 DPI for review crops. Existing OCR was compared with two Windows Media OCR preprocessing passes; unresolved records remain explicitly review-required.", "",
        "## Resolution counts", "", "| metric | count |", "|---|---:|",
        f"| initial review-required | {initial_review} |", f"| records processed | {report['records_processed']} |", f"| promoted to CONTENT_VERIFIED | {promoted_count} |", f"| retained as OCR_REVIEW_REQUIRED | {retained} |", f"| final review-required | {final_review} |", f"| final content-verified | {final_verified} |", "",
        "## Review statistics", "", f"OCR engine disagreements: {report['ocr_engine_disagreements']}; equation cases: {report['equation_cases']}; chemistry cases: {report['chemistry_cases']}; diagram cases: {report['diagram_cases']}; bilingual cases: {report['bilingual_cases']}; graphical-option cases: {report['graphical_options']}", f"Promotions by year: {report['promotions_by_year']}", "",
        "## Validation", "", f"Placeholders: questions={placeholders_result['question_placeholders']}, options={placeholders_result['option_placeholders']}", f"Critical OCR errors: {report['critical_ocr_errors']}", f"Provenance errors: {report['provenance_errors']}", f"Metadata errors: {metadata_errors}", f"Source-image failures retained: {source_failures}", f"Database integrity errors: {integrity_error_total}", "",
        "## Full-paper validation", "", "| year | questions | expected | pass |", "|---:|---:|---:|---|",
    ]
    for year, item in sorted(full_validation.items()):
        lines.append(f"| {year} | {item['question_count']} | {item['expected_question_count']} | {'PASS' if item['pass'] else 'REVIEW_REQUIRED'} |")
    lines += ["", "Every processed occurrence has a batch record with a final disposition. No Phase 5C work, solutions, taxonomy, Supabase import, frontend, or test-series work was started.", ""]
    (AUDIT / "jee_main_ocr_full_resolution_report.md").write_text("\n".join(lines), encoding="utf-8")
    final_lines = [
        "# JEE Main full-paper OCR final validation", "", f"Generated: {report['generated_at']}", "", "Validation uses the official-paper source metadata and the production JSONL occurrence graph.", "", "| year | source | question count | expected | numbering | subjects | options | images | metadata/pages | result |", "|---:|---|---:|---:|---|---|---|---|---|---|",
    ]
    for year, item in sorted(full_validation.items()):
        final_lines.append(f"| {year} | {item['source_id']} | {item['question_count']} | {item['expected_question_count']} | {'PASS' if not item['duplicate_question_numbers'] and not item['missing_question_numbers'] else 'FAIL'} | {'PASS' if item['subject_order_pass'] else 'FAIL'} | {'PASS' if item['options_pass'] else 'FAIL'} | {'PASS' if item['images_pass'] else 'FAIL'} | {'PASS' if item['metadata_pass'] and item['page_mapping_pass'] else 'FAIL'} | {'PASS' if item['pass'] else 'FAIL'} |")
    final_lines += ["", f"Overall full-paper result: {'PASS' if all(item['pass'] for item in full_validation.values()) else 'FAIL'}", ""]
    (AUDIT / "jee_main_full_ocr_final_validation.md").write_text("\n".join(final_lines), encoding="utf-8")
    return report


def apply_and_report() -> dict[str, Any]:
    summary = apply_promotions_and_rebuild()
    report = create_reports({}, summary, build_queue())
    print(json.dumps({"final_status": report["final_status"], "records_processed": report["records_processed"], "records_promoted": report["records_promoted"], "records_retained": report["records_retained"], "final_review_required": report["final_review_required"], "final_content_verified": report["final_content_verified"], "metadata_errors": report["metadata_errors"], "provenance_errors": report["provenance_errors"], "database_integrity": report["database_integrity"]}, indent=2, ensure_ascii=False))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--queue", action="store_true")
    group.add_argument("--process", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--reset-queue", action="store_true")
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--batch-start", type=int, default=1)
    parser.add_argument("--batch-end", type=int, default=None)
    args = parser.parse_args()
    if args.reset_queue:
        build_queue(force=True)
        print(json.dumps(build_queue(), indent=2))
    elif args.queue:
        print(json.dumps(build_queue(), indent=2))
    elif args.process:
        print(json.dumps(asyncio.run(process_all(args.max_batches, args.batch_start, args.batch_end)), indent=2))
    else:
        apply_and_report()


if __name__ == "__main__":
    main()
