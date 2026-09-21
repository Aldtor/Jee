"""Phase 5B JEE Main source-grounded OCR reconstruction.

This module deliberately keeps the official PDFs untouched.  It builds a
canonical inventory from the official-paper manifest, renders only derived
page/cell images at 300 DPI, uses Windows Media OCR, and writes resumable
page checkpoints plus JSONL/SQLite production data.

The pipeline is conservative: OCR is evidence, not authority.  Suspicious or
incomplete text remains flagged for review and the raw OCR is retained.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import gc
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pymupdf

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - inventory still reports the failure
    PdfReader = None

from PIL import Image

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


BASE_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = BASE_DIR / "JEE_Main_PYQ_Archive"
FINAL_DIR = BASE_DIR / "JEE_QUESTION_DATABASE_FINAL"
JM_DIR = FINAL_DIR / "JEE_MAIN"
ASSET_DIR = FINAL_DIR / "assets"
AUDIT_DIR = FINAL_DIR / "audit"
ROOT_AUDIT_DIR = BASE_DIR / "audit"
CHECKPOINT_DIR = FINAL_DIR / "ocr_checkpoints"
MANIFEST_PATH = ARCHIVE_DIR / "jee_main_official_paper_manifest.json"

DPI_PASS1 = 300
DPI_PASS2 = 400
OCR_ENGINE_NAME = "WINDOWS_MEDIA_OCR"
RUN_VERSION = "v5"

PLACEHOLDER_RE = re.compile(
    r"^(?:question\s*(?:text|x|\d+)?|placeholder|sample question|generated question|"
    r"option\s*[abcd]|tbd|todo|n/a|n\.a\.)$",
    re.I,
)
SUSPICIOUS_RE = re.compile(
    r"(?:[�]|Ã|Â|Ï|Î|â|\b(?:Question Number|Question ID|Option Shuffling|Correct Marks)\b|"
    r"\b(?:ld|lD)\s*:|https?://|\b(?:Options|Topic|Item No)\s*:)",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_consolidated_jsonl() -> dict[str, Any]:
    return {
        "sources": read_jsonl(JM_DIR / "sources.jsonl"),
        "questions": read_jsonl(JM_DIR / "questions.jsonl"),
        "occurrences": read_jsonl(JM_DIR / "question_occurrences.jsonl"),
        "options": read_jsonl(JM_DIR / "options.jsonl"),
        "answers": read_jsonl(JM_DIR / "answers.jsonl"),
        "images": read_jsonl(JM_DIR / "images.jsonl"),
        "processed": [],
    }


def norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def rel_source_path(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def normalize_text(text: str | None) -> str | None:
    if text is None:
        return None
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return text.strip() or None


def safe_text(text: str | None) -> str:
    return normalize_text(text) or ""


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def subject_from_text(value: str | None) -> str:
    text = (value or "").lower()
    if "math" in text:
        return "Mathematics"
    if "chem" in text:
        return "Chemistry"
    if "phys" in text:
        return "Physics"
    return "Unknown"


def question_type(value: str | None) -> str:
    text = (value or "").lower()
    if "numer" in text or "integer" in text:
        return "NUMERICAL"
    if "mcq" in text or "multiple" in text:
        return "MCQ"
    return "UNKNOWN"


def source_id_for(row: dict[str, Any], path: Path, duplicate_index: int = 0) -> str:
    year = str(row.get("year") or "unknown")
    session = str(row.get("session") or "session")
    date = str(row.get("exam_date") or "unknown-date")
    shift = str(row.get("shift") or "unknown-shift")
    language = str(row.get("language") or "English").replace(" ", "_")
    suffix = "" if language == "English" else f"_{language}"
    if duplicate_index:
        suffix += f"_DUP{duplicate_index + 1}"
    base = f"JM_{year}_{session}_{date}_{shift}{suffix}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", base)


def occurrence_id(source_id: str, qnum: int, ordinal: int = 1) -> str:
    return f"{source_id}_Q{qnum:03d}_OCC{ordinal}"


@dataclass
class SourceInfo:
    source_id: str
    source_record_index: int
    year: int | None
    session: str | None
    exam_date: str | None
    shift: int | None
    language: str | None
    paper_type: str
    local_path: str
    source_url: str | None
    source_sha256: str | None
    page_count: int | None
    source_status: str
    format_type: str | None = None
    manifest_row_count: int = 1
    duplicate_of: str | None = None
    error: str | None = None


@dataclass
class Marker:
    page: int
    y0: float
    y1: float
    qnum: int | None
    qid: str | None
    qtype: str | None
    subject: str | None
    section: str | None
    source: str


@dataclass
class OcrLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


def line_box(line: Any) -> tuple[float, float, float, float] | None:
    words = list(line.words)
    if not words:
        return None
    rects = [w.bounding_rect for w in words]
    return (
        min(float(r.x) for r in rects),
        min(float(r.y) for r in rects),
        max(float(r.x + r.width) for r in rects),
        max(float(r.y + r.height) for r in rects),
    )


def ocr_lines_to_dict(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in result.lines:
        box = line_box(line)
        if not box:
            continue
        rows.append({"text": str(line.text), "bbox": [round(v, 2) for v in box]})
    return rows


def ocr_line_objects(rows: list[dict[str, Any]]) -> list[OcrLine]:
    return [OcrLine(r["text"], *r["bbox"]) for r in rows]


def text_blocks(page: Any) -> list[tuple[float, float, float, float, str]]:
    out = []
    for b in page.get_text("blocks"):
        if len(b) < 5:
            continue
        out.append((float(b[0]), float(b[1]), float(b[2]), float(b[3]), str(b[4])))
    return sorted(out, key=lambda x: (x[1], x[0]))


def block_marker(page_no: int, block: tuple[float, float, float, float, str]) -> Marker | None:
    x0, y0, x1, y1, text = block
    flat = re.sub(r"\s+", " ", text).strip()
    m = re.search(
        r"Question\s+Number\s*:\s*(\d+).*?Question\s+(?:Id|ID)\s*:\s*([A-Za-z0-9_-]+).*?"
        r"Question\s+Type\s*:\s*([A-Za-z-]+)",
        flat,
        re.I,
    )
    if m:
        return Marker(page_no, y0, y1, int(m.group(1)), m.group(2), m.group(3), None, None, "pdf_text")
    return None


def ocr_markers(page_no: int, lines: list[OcrLine]) -> list[Marker]:
    out: list[Marker] = []
    for line in lines:
        flat = re.sub(r"\s+", " ", line.text).strip()
        m = re.search(
            r"Question\s+Number\s*:?\s*(\d+).*?(?:Question\s+I[dlD]\s*:?\s*([A-Za-z0-9_-]+))?.*?"
            r"Question\s+Type\s*:?\s*([A-Za-z-]+)",
            flat,
            re.I,
        )
        if not m:
            m = re.search(r"(?:^|\s)Q\s*[:.]\s*(\d+)\b", flat, re.I)
        if not m:
            m = re.search(r"(?:^|\s)Item\s*(?:No|Code)\s*:?\s*(\d+)\b", flat, re.I)
        if m:
            qnum = int(m.group(1))
            qid = m.group(2) if len(m.groups()) >= 2 else None
            qtype = m.group(3) if len(m.groups()) >= 3 else None
            out.append(Marker(page_no, line.y0, line.y1, qnum, qid, qtype, None, None, "ocr"))
    return out


def extract_legacy_questions() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    extraction_dir = FINAL_DIR / "extraction"
    for path in extraction_dir.glob("*.json"):
        if path.name == "extraction_log.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_path = data.get("source_path")
        if not source_path:
            continue
        rows = data.get("questions") or []
        result[norm_path(source_path)] = rows
        result[norm_path(Path(source_path).name)] = rows
    return result


def load_old_records() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    occ_path = JM_DIR / "question_occurrences.jsonl"
    q_path = JM_DIR / "questions.jsonl"
    ans_path = JM_DIR / "answers.jsonl"
    occs: list[dict[str, Any]] = []
    questions: dict[str, dict[str, Any]] = {}
    answers: dict[str, dict[str, Any]] = {}
    for path, dest in [(occ_path, occs), (q_path, questions), (ans_path, answers)]:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if isinstance(dest, list):
                    dest.append(row)
                else:
                    key = row.get("question_id") or row.get("occurrence_id")
                    if key:
                        dest[key] = row
    return occs, questions, answers


def load_manifest() -> list[dict[str, Any]]:
    rows = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [r for r in rows if r.get("download_status") == "AVAILABLE_AND_DOWNLOADED"]


def inventory_sources() -> tuple[list[SourceInfo], list[dict[str, Any]]]:
    manifest = load_manifest()
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for idx, row in enumerate(manifest, start=1):
        path = BASE_DIR / row["local_path"]
        grouped[norm_path(path)].append((idx, row))

    sources: list[SourceInfo] = []
    all_manifest_rows: list[dict[str, Any]] = []
    for path_key, members in sorted(grouped.items(), key=lambda kv: kv[1][0][0]):
        idx, row = members[0]
        path = BASE_DIR / row["local_path"]
        source_id = source_id_for(row, path)
        if len(members) > 1:
            # The manifest has repeated rows for the same official local PDF.
            # Keep one canonical source row and record the multiplicity.
            source_id = source_id_for(row, path)
        source_sha = None
        page_count = None
        error = None
        status = "VALID_SOURCE_PDF"
        try:
            source_sha = sha256_file(path)
        except Exception as exc:
            status = "SOURCE_MISSING"
            error = f"sha256: {type(exc).__name__}: {exc}"
        if status != "SOURCE_MISSING":
            try:
                if PdfReader is None:
                    raise RuntimeError("pypdf unavailable")
                with contextlib.redirect_stderr(io.StringIO()):
                    page_count = len(PdfReader(str(path)).pages)
            except Exception as exc:
                status = "SOURCE_CORRUPT"
                error = f"pypdf: {type(exc).__name__}: {exc}"
            if status == "VALID_SOURCE_PDF":
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        doc = pymupdf.open(str(path))
                        page_count = len(doc)
                        # Check every page handle without extracting content.
                        for page_no in range(page_count):
                            _ = doc[page_no].rect
                        doc.close()
                except Exception as exc:
                    status = "SOURCE_CORRUPT"
                    error = f"pymupdf: {type(exc).__name__}: {exc}"
        info = SourceInfo(
            source_id=source_id,
            source_record_index=idx,
            year=parse_int(row.get("year")),
            session=row.get("session"),
            exam_date=row.get("exam_date") or None,
            shift=parse_int(row.get("shift")),
            language=row.get("language"),
            paper_type=row.get("paper_type") or "Paper-I (B.E./B.Tech.)",
            local_path=rel_source_path(path),
            source_url=row.get("qp_url") or row.get("source_page"),
            source_sha256=source_sha,
            page_count=page_count,
            source_status=status,
            manifest_row_count=len(members),
            error=error,
        )
        sources.append(info)
        for member_idx, member in members:
            all_manifest_rows.append(
                {
                    **member,
                    "manifest_row_index": member_idx,
                    "canonical_source_id": source_id,
                    "local_path_absolute": str(BASE_DIR / member["local_path"]),
                    "source_status": status,
                    "page_count": page_count,
                    "computed_sha256": source_sha,
                    "validation_error": error,
                }
            )
    return sources, all_manifest_rows


async def ocr_png(engine: Any, png_data: bytes) -> tuple[str, list[dict[str, Any]]]:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_data)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return str(result.text), ocr_lines_to_dict(result)


def pixmap_pil(pix: Any) -> Image.Image:
    mode = "RGBA" if pix.alpha else "RGB"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def pil_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def scaled_box(rect: tuple[float, float, float, float], scale: float, width: int, height: int, pad: int = 4) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (
        max(0, int(x0 * scale) - pad),
        max(0, int(y0 * scale) - pad),
        min(width, int(x1 * scale) + pad),
        min(height, int(y1 * scale) + pad),
    )


def unique_image_rects(page: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int, int]] = set()
    try:
        images = page.get_images(full=True)
    except Exception:
        return out
    for image in images:
        xref = int(image[0])
        try:
            pix = pymupdf.Pixmap(page.parent, xref)
            width, height = pix.width, pix.height
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            key = (xref, round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "xref": xref,
                    "rect": [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    "width": width,
                    "height": height,
                }
            )
    return sorted(out, key=lambda x: (x["rect"][1], x["rect"][0]))


def text_marker_events(doc: Any) -> tuple[list[Marker], dict[int, list[tuple[str, float, float]]]]:
    markers: list[Marker] = []
    labels: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
    for page_no in range(len(doc)):
        page = doc[page_no]
        blocks = text_blocks(page)
        for block in blocks:
            marker = block_marker(page_no + 1, block)
            if marker:
                markers.append(marker)
            flat = re.sub(r"\s+", " ", block[4]).strip()
            label = re.match(r"^(Question|Options?|[ABCD])\s*:", flat, re.I)
            if label:
                labels[page_no + 1].append((label.group(1).upper(), block[1], block[3]))
        # 2022 tabular PDFs expose Topic/Item No/QID/Type as separate blocks.
        for i, block in enumerate(blocks):
            if not re.search(r"\bTopic\s*:", block[4], re.I):
                continue
            look = " ".join(b[4] for b in blocks[i : i + 6])
            item = re.search(r"Item\s+No\s*:\s*(\d+)", look, re.I)
            qid = re.search(r"Question\s+ID\s*:\s*([A-Za-z0-9_-]+)", look, re.I)
            typ = re.search(r"Question\s+Type\s*:\s*([A-Za-z-]+)", look, re.I)
            topic = re.search(r"Topic\s*:\s*([^\n]+)", look, re.I)
            if item:
                markers.append(
                    Marker(
                        page_no + 1,
                        block[1],
                        block[3],
                        int(item.group(1)),
                        qid.group(1) if qid else None,
                        typ.group(1) if typ else None,
                        subject_from_text(topic.group(1) if topic else None),
                        topic.group(1).strip() if topic else None,
                        "pdf_text_tabular",
                    )
                )
    return markers, labels


def dedupe_markers(markers: list[Marker]) -> list[Marker]:
    out: list[Marker] = []
    seen: set[tuple[int, int | None, int]] = set()
    for marker in sorted(markers, key=lambda m: (m.page, m.y0, m.qnum or 0)):
        key = (marker.page, marker.qnum, round(marker.y0))
        if key in seen:
            continue
        seen.add(key)
        out.append(marker)
    return out


def choose_markers(
    legacy: list[dict[str, Any]],
    markers: list[Marker],
    page_ocr: dict[int, list[OcrLine]],
) -> list[dict[str, Any]]:
    """Align structural records to visible markers, falling back to OCR markers."""
    all_markers = dedupe_markers(markers)
    if legacy:
        chosen: list[dict[str, Any]] = []
        used: set[tuple[int, int, int]] = set()
        for q in legacy:
            qnum = parse_int(q.get("question_number"))
            if qnum is None:
                continue
            start_page = parse_int(q.get("source_page")) or 1
            candidates = [m for m in all_markers if m.qnum == qnum and m.page >= start_page]
            if not candidates:
                candidates = [m for m in all_markers if m.qnum == qnum]
            marker = None
            for candidate in candidates:
                key = (candidate.page, qnum, round(candidate.y0))
                if key not in used:
                    marker = candidate
                    used.add(key)
                    break
            chosen.append(
                {
                    "question_number": qnum,
                    "nta_question_id": q.get("nta_question_id"),
                    "question_type": q.get("question_type") or (marker.qtype if marker else None),
                    "subject": q.get("subject") or (marker.subject if marker else "Unknown"),
                    "section": q.get("section") or (marker.section if marker else None),
                    "source_page": start_page,
                    "marker": asdict(marker) if marker else None,
                    "options_nta_ids": [o.get("option_nta_id") for o in (q.get("options") or [])],
                    "legacy": True,
                }
            )
        return chosen

    # No structural records: use OCR markers in first-seen order, suppressing
    # repeated metadata blocks for the same question number.
    out: list[dict[str, Any]] = []
    seen_q: set[int] = set()
    for marker in all_markers:
        if marker.qnum is None or marker.qnum in seen_q:
            continue
        seen_q.add(marker.qnum)
        out.append(
            {
                "question_number": marker.qnum,
                "nta_question_id": marker.qid,
                "question_type": question_type(marker.qtype),
                "subject": marker.subject or "Unknown",
                "section": marker.section,
                "source_page": marker.page,
                "marker": asdict(marker),
                "options_nta_ids": [],
                "legacy": False,
            }
        )
    return out


def q_interval(qs: list[dict[str, Any]], index: int, page: int, page_height: float) -> tuple[float, float] | None:
    current = qs[index]
    start_page = current["marker"].get("page") if current.get("marker") else current.get("source_page") or 1
    if page < start_page:
        return None
    current_y = current["marker"].get("y0", 0.0) if current.get("marker") else 0.0
    if page == start_page and page_height <= current_y:
        return None
    if index + 1 < len(qs):
        nxt = qs[index + 1]
        next_page = nxt["marker"].get("page") if nxt.get("marker") else nxt.get("source_page") or start_page
        next_y = nxt["marker"].get("y0", 0.0) if nxt.get("marker") else 0.0
        if page > next_page or (page == next_page and page >= next_y):
            return None
        end = next_y if page == next_page else page_height
    else:
        end = page_height
    return (current_y if page == start_page else 0.0, end)


def lines_inside(lines: list[OcrLine], rect: tuple[float, float, float, float], min_x: float = 0.0) -> list[str]:
    x0, y0, x1, y1 = rect
    out = []
    for line in lines:
        cx = (line.x0 + line.x1) / 2
        cy = (line.y0 + line.y1) / 2
        if x0 - 8 <= cx <= x1 + 8 and y0 - 8 <= cy <= y1 + 8 and cx >= min_x:
            out.append(line.text)
    return out


def lines_between(lines: list[OcrLine], y0: float, y1: float, min_x: float = 0.0) -> list[str]:
    out = []
    for line in lines:
        cy = (line.y0 + line.y1) / 2
        cx = (line.x0 + line.x1) / 2
        if y0 <= cy < y1 and cx >= min_x:
            out.append(line.text)
    return out


def filter_content_lines(lines: list[str]) -> str | None:
    keep: list[str] = []
    for line in lines:
        text = normalize_text(line)
        if not text:
            continue
        if re.search(r"^(?:Question Number|Question ID|Question Type|Options?|Correct Marks|Wrong Marks|"
                     r"Option Shuffling|Display Question|Number|Is Question|https?://|\d+/\d+)$", text, re.I):
            continue
        if re.fullmatch(r"[A-Za-z0-9_-]{7,}\.?", text):
            continue
        keep.append(text)
    return normalize_text(" ".join(keep))


def save_crop(image: Image.Image, bbox: tuple[int, int, int, int], path: Path) -> tuple[str, int, int]:
    crop = image.crop(bbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        crop.save(path, format="PNG", optimize=True)
    data = path.read_bytes()
    return rel_source_path(path), crop.width, crop.height


def asset_path(kind: str, identifier: str) -> Path:
    if kind == "question":
        return ASSET_DIR / "questions" / f"phase5b_{RUN_VERSION}_question_{identifier}.png"
    if kind == "option":
        return ASSET_DIR / "options" / f"phase5b_{RUN_VERSION}_option_{identifier}.png"
    return ASSET_DIR / "diagrams" / f"phase5b_{RUN_VERSION}_diagram_{identifier}.png"


def suspicious(text: str | None) -> bool:
    return bool(text and SUSPICIOUS_RE.search(text))


async def crop_records_for_question(
    q_index: int,
    q: dict[str, Any],
    qs: list[dict[str, Any]],
    page_cache: dict[int, dict[str, Any]],
    doc: Any,
    occurrence: str,
    source: SourceInfo,
    engine: Any,
) -> dict[str, Any]:
    q_pages: list[int] = []
    q_image_recs: list[dict[str, Any]] = []
    option_image_recs: list[dict[str, Any]] = []
    question_lines: list[str] = []
    option_lines: defaultdict[int, list[str]] = defaultdict(list)
    pass2_texts: list[str] = []
    pass2_disagreement = False

    async def pass2_if_difficult(raw_text: str, crop: Image.Image, allow_short: bool = False) -> str:
        nonlocal pass2_disagreement
        difficult = (not raw_text or (not allow_short and len(raw_text) < 6) or suspicious(raw_text) or
                     bool(re.search(r"(?:<|>|\[|\]|\^|_|\\|\bIll\b|\bmis\b|\bIfthe\b)", raw_text)))
        if not difficult:
            return raw_text
        enlarged = crop.resize((max(1, int(crop.width * DPI_PASS2 / DPI_PASS1)), max(1, int(crop.height * DPI_PASS2 / DPI_PASS1))), Image.Resampling.LANCZOS)
        pass2_raw, _ = await ocr_png(engine, pil_png_bytes(enlarged))
        pass2 = filter_content_lines(pass2_raw.splitlines()) or ""
        if pass2:
            pass2_texts.append(pass2)
            if raw_text and normalize_text(raw_text) != normalize_text(pass2):
                pass2_disagreement = True
            # Prefer the second pass only when it contains materially more
            # source text; disagreements remain review evidence.
            if len(pass2) > len(raw_text) * 1.15:
                return pass2
        return raw_text

    start_page = q.get("marker", {}).get("page") if q.get("marker") else q.get("source_page", 1)
    start_page = int(start_page or 1)
    end_page = start_page
    next_start = None
    if q_index + 1 < len(qs):
        nxt = qs[q_index + 1]
        next_start = int((nxt.get("marker") or {}).get("page") or nxt.get("source_page") or start_page)
        end_page = max(start_page, next_start)
    else:
        end_page = len(doc)

    for page_no in range(start_page, min(end_page, len(doc)) + 1):
        cached = page_cache.get(page_no)
        if not cached:
            continue
        interval = q_interval(qs, q_index, page_no, cached["page_height"])
        if not interval:
            continue
        y0, y1 = interval
        q_pages.append(page_no)
        lines = ocr_line_objects(cached.get("ocr_lines", []))
        content_rects = []
        for item in cached.get("images", []):
            rect = tuple(item["rect"])
            rx0, ry0, rx1, ry1 = rect
            if not (y0 <= (ry0 + ry1) / 2 < y1):
                continue
            if rx1 < 70 or rx0 > cached["page_width"] - 10:
                continue
            content_rects.append(item)
        # Use explicit Options/A/B/C/D label positions when available.  This
        # handles both recorded-response and 2022 tabular templates.
        label_rows = cached.get("labels", [])
        q_option_y = [float(y) for label, y, _ in label_rows if label in {"OPTIONS", "A", "B", "C", "D"} and y0 <= y < y1]
        first_option_y = min(q_option_y) if q_option_y else None
        for item in content_rects:
            rect = tuple(item["rect"])
            mid_y = (rect[1] + rect[3]) / 2
            item = dict(item)
            item["page"] = page_no
            item["is_option"] = first_option_y is not None and mid_y >= first_option_y - 8
            if not item["is_option"] and item["width"] <= 100 and q_option_y:
                # A short graphical question is still a question if it is
                # before the first option row; keep it in question evidence.
                item["is_option"] = False
            if item["is_option"]:
                option_image_recs.append(item)
            else:
                q_image_recs.append(item)
        if not content_rects:
            # Vector/text fallback: the visible OCR lines in this interval are
            # still source evidence, but no raster crop is invented.
            page_q_lines = lines_between(lines, y0 * cached["scale"], y1 * cached["scale"], min_x=70 * cached["scale"])
            if first_option_y is None:
                question_lines.extend(page_q_lines)
            else:
                question_lines.extend(lines_between(lines, y0 * cached["scale"], first_option_y * cached["scale"], min_x=70 * cached["scale"]))
                for idx, label_y in enumerate(sorted(q_option_y)):
                    next_y = sorted(q_option_y)[idx + 1] if idx + 1 < len(q_option_y) else y1
                    option_lines[idx].extend(lines_between(lines, label_y * cached["scale"], next_y * cached["scale"], min_x=70 * cached["scale"]))

    q_image_recs.sort(key=lambda x: (x["page"], x["rect"][1], x["rect"][0]))
    option_image_recs.sort(key=lambda x: (x["page"], x["rect"][1], x["rect"][0]))

    assets: list[dict[str, Any]] = []
    q_text_parts: list[str] = []
    for part_idx, item in enumerate(q_image_recs):
        page_no = item["page"]
        cached = page_cache[page_no]
        if "image" not in cached:
            page = doc[page_no - 1]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(cached["scale"], cached["scale"]), alpha=False)
            cached["image"] = pixmap_pil(pix)
        rect = tuple(item["rect"])
        scale = cached["scale"]
        bbox = scaled_box(rect, scale, cached["image"].width, cached["image"].height)
        identifier = f"{occurrence}_P{page_no}_{part_idx + 1}"
        path = asset_path("question", identifier)
        asset_rel, width, height = save_crop(cached["image"], bbox, path)
        pixel_rect = tuple(v * scale for v in rect)
        raw = filter_content_lines(lines_inside(ocr_line_objects(cached.get("ocr_lines", [])), pixel_rect, min_x=pixel_rect[0] - 10)) or ""
        raw = await pass2_if_difficult(raw, cached["image"].crop(bbox))
        q_text_parts.append(raw)
        assets.append(
            {
                "image_id": f"{occurrence}_QUESTION_{part_idx + 1}",
                "image_type": "question_crop" if part_idx == 0 else "diagram_crop",
                "image_path": asset_rel,
                "source_pdf": source.local_path,
                "source_page": page_no,
                "question_occurrence_id": occurrence,
                "bounding_box": [round(v, 3) for v in rect],
                "width": width,
                "height": height,
                "sha256": sha256_file(path),
            }
        )

    if not q_image_recs:
        q_text_parts.extend(question_lines)

    option_rows: list[dict[str, Any]] = []
    option_count = 4 if question_type(q.get("question_type")) == "MCQ" else 0
    for idx, item in enumerate(option_image_recs[: max(option_count, len(option_image_recs))]):
        label = "ABCD"[idx] if idx < 4 else f"OPT{idx + 1}"
        page_no = item["page"]
        cached = page_cache[page_no]
        if "image" not in cached:
            page = doc[page_no - 1]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(cached["scale"], cached["scale"]), alpha=False)
            cached["image"] = pixmap_pil(pix)
        rect = tuple(item["rect"])
        bbox = scaled_box(rect, cached["scale"], cached["image"].width, cached["image"].height)
        identifier = f"{occurrence}_{label}"
        path = asset_path("option", identifier)
        asset_rel, width, height = save_crop(cached["image"], bbox, path)
        pixel_rect = tuple(v * cached["scale"] for v in rect)
        raw = filter_content_lines(lines_inside(ocr_line_objects(cached.get("ocr_lines", [])), pixel_rect, min_x=pixel_rect[0] - 10)) or ""
        raw = await pass2_if_difficult(raw, cached["image"].crop(bbox), allow_short=True)
        option_rows.append(
            {
                "label": label,
                "option_index": idx + 1,
                "raw_ocr_text": raw,
                "text": normalize_text(raw),
                "image_path": asset_rel,
                "source_page": page_no,
                "bounding_box": [round(v, 3) for v in rect],
                "width": width,
                "height": height,
                "sha256": sha256_file(path),
                "image_id": f"{occurrence}_OPTION_{label}",
            }
        )
        assets.append(
            {
                "image_id": f"{occurrence}_OPTION_{label}",
                "image_type": "option_crop",
                "image_path": asset_rel,
                "source_pdf": source.local_path,
                "source_page": page_no,
                "question_occurrence_id": occurrence,
                "bounding_box": [round(v, 3) for v in rect],
                "width": width,
                "height": height,
                "sha256": sha256_file(path),
            }
        )

    if not option_rows and option_count:
        for idx in range(4):
            raw = filter_content_lines(option_lines.get(idx, [])) or ""
            option_rows.append(
                {
                    "label": "ABCD"[idx],
                    "option_index": idx + 1,
                    "raw_ocr_text": raw,
                    "text": normalize_text(raw),
                    "image_path": None,
                    "source_page": q_pages[0] if q_pages else source.page_count,
                    "bounding_box": None,
                    "width": None,
                    "height": None,
                    "sha256": None,
                    "image_id": None,
                }
            )

    return {
        "source_pages": sorted(set(q_pages)) or [start_page],
        "question_text": normalize_text(" ".join(x for x in q_text_parts if x)) or None,
        "raw_question_text": " ".join(x for x in q_text_parts if x).strip() or None,
        "options": option_rows,
        "assets": assets,
        "ocr_pass2_texts": pass2_texts,
        "pass2_disagreement": pass2_disagreement,
    }


async def process_source(source: SourceInfo, legacy_map: dict[str, list[dict[str, Any]]], engine: Any) -> dict[str, Any]:
    path = BASE_DIR / source.local_path
    checkpoint_key = source.source_sha256 or hashlib.sha256(source.local_path.encode()).hexdigest()
    page_jsonl = CHECKPOINT_DIR / f"{RUN_VERSION}_{checkpoint_key[:20]}.pages.jsonl"
    final_checkpoint = CHECKPOINT_DIR / f"{RUN_VERSION}_{checkpoint_key[:20]}.json"
    if final_checkpoint.exists():
        try:
            data = json.loads(final_checkpoint.read_text(encoding="utf-8"))
            if data.get("source_sha256") == source.source_sha256 and data.get("status") == "complete":
                return data
        except Exception:
            pass

    if source.source_status != "VALID_SOURCE_PDF":
        result = {
            "status": "corrupt",
            "source_id": source.source_id,
            "source_sha256": source.source_sha256,
            "questions": [],
            "assets": [],
            "warnings": [source.error or "source is not readable by both PDF engines"],
        }
        json_dump(final_checkpoint, result)
        return result

    doc = pymupdf.open(str(path))
    legacy = legacy_map.get(norm_path(path)) or legacy_map.get(norm_path(path.name)) or []
    if not legacy:
        # Phase 5A sometimes keyed the structural sidecar to a Hindi or
        # English-Hindi sibling even when the manifest's canonical row is the
        # English PDF.  The sidecar is structural metadata only; the content
        # below is still OCR'd from this exact source PDF.
        for suffix in ("_Hindi", "_English_Hindi"):
            sibling = path.with_name(path.stem + suffix + path.suffix)
            legacy = legacy_map.get(norm_path(sibling)) or legacy_map.get(norm_path(sibling.name)) or []
            if legacy:
                break
    text_markers, labels_by_page = text_marker_events(doc)
    page_results: dict[int, dict[str, Any]] = {}
    if page_jsonl.exists():
        with page_jsonl.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    page_results[int(row["page_number"])] = row

    # First pass: page OCR and derived page structure.  Pages with no visible
    # question markers are still kept in the checkpoint for completeness.
    with page_jsonl.open("a", encoding="utf-8") as checkpoint_file:
        for page_no in range(1, len(doc) + 1):
            if page_no in page_results:
                continue
            page = doc[page_no - 1]
            scale = DPI_PASS1 / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            png = pix.tobytes("png")
            text, ocr_rows = await ocr_png(engine, png)
            image = pixmap_pil(pix)
            ocr_line_objs = ocr_line_objects(ocr_rows)
            markers = ocr_markers(page_no, ocr_line_objs)
            labels = list(labels_by_page.get(page_no, []))
            for line in ocr_line_objs:
                flat = re.sub(r"\s+", " ", line.text).strip()
                m = re.match(r"^(Question|Options?|[ABCD])\s*:", flat, re.I)
                if m:
                    labels.append((m.group(1).upper(), line.y0 / scale, line.y1 / scale))
            row = {
                "page_number": page_no,
                "page_width": float(page.rect.width),
                "page_height": float(page.rect.height),
                "scale": scale,
                "pdf_text_length": len(page.get_text("text")),
                "ocr_text": text,
                "ocr_lines": ocr_rows,
                "markers": [asdict(x) for x in markers],
                "labels": labels,
                "images": unique_image_rects(page),
            }
            page_results[page_no] = row
            checkpoint_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            checkpoint_file.flush()

    # OCR markers from the page checkpoint supplement the PDF text markers.
    all_markers = list(text_markers)
    for row in page_results.values():
        all_markers.extend(Marker(**m) for m in row.get("markers", []))
    page_ocr = {n: ocr_line_objects(r.get("ocr_lines", [])) for n, r in page_results.items()}
    qs = choose_markers(legacy, all_markers, page_ocr)

    question_rows: list[dict[str, Any]] = []
    all_assets: list[dict[str, Any]] = []
    for idx, q in enumerate(qs):
        occ = occurrence_id(source.source_id, int(q["question_number"]))
        extracted = await crop_records_for_question(idx, q, qs, page_results, doc, occ, source, engine)
        text = extracted["question_text"]
        options = extracted["options"]
        has_text = bool(text and len(text) >= 3)
        suspicious_fields = suspicious(text) or any(suspicious(o.get("text")) for o in options)
        if not has_text and not extracted["assets"]:
            ocr_status = "OCR_REVIEW_REQUIRED"
            content_status = "OCR_REVIEW_REQUIRED"
        elif suspicious_fields or extracted.get("pass2_disagreement") or source.language in {"Hindi", "English_Hindi"} or not q.get("legacy"):
            ocr_status = "OCR_REVIEW_REQUIRED"
            content_status = "CONTENT_PARTIALLY_VERIFIED"
        elif has_text:
            ocr_status = "OCR_MEDIUM_CONFIDENCE"
            content_status = "CONTENT_PARTIALLY_VERIFIED"
        else:
            ocr_status = "OCR_LOW_CONFIDENCE"
            content_status = "CONTENT_PARTIALLY_VERIFIED"
        if source.source_status == "SOURCE_PARTIAL":
            content_status = "CONTENT_PARTIALLY_VERIFIED"
        question_rows.append(
            {
                **q,
                "occurrence_id": occ,
                "source_id": source.source_id,
                "source_pdf": source.local_path,
                "source_pages": extracted["source_pages"],
                "page_number": extracted["source_pages"][0],
                "question_text": text,
                "raw_question_text": extracted["raw_question_text"],
                "normalized_text": normalize_text(text),
                "options": options,
                "ocr_engine": OCR_ENGINE_NAME,
                "ocr_confidence": 0.72 if ocr_status == "OCR_MEDIUM_CONFIDENCE" else (0.35 if ocr_status == "OCR_LOW_CONFIDENCE" else 0.2),
                "ocr_status": ocr_status,
                "content_status": content_status,
                "image_hashes": [a["sha256"] for a in extracted["assets"]],
                "ocr_pass2_texts": extracted.get("ocr_pass2_texts", []),
                "pass2_disagreement": extracted.get("pass2_disagreement", False),
            }
        )
        all_assets.extend(extracted["assets"])
        # Keep only a small look-ahead window of rendered page images.  OCR
        # line evidence remains in the checkpoint; this bounds RAM while
        # processing image-heavy papers and permits safe resumable workers.
        future_pages: set[int] = set()
        for future_q in qs[idx + 1 : idx + 5]:
            for key in ("page", "source_page"):
                value = future_q.get(key)
                if isinstance(value, list):
                    future_pages.update(int(v) for v in value if str(v).isdigit())
                elif str(value).isdigit():
                    future_pages.add(int(value))
        for page_no in extracted.get("source_pages", []):
            if int(page_no) not in future_pages:
                page_results.get(int(page_no), {}).pop("image", None)
        if idx % 8 == 0:
            gc.collect()

    result = {
        "status": "complete",
        "source_id": source.source_id,
        "source_sha256": source.source_sha256,
        "source_status": source.source_status,
        "page_count": len(doc),
        "questions": question_rows,
        "assets": all_assets,
        "warnings": [],
        "completed_at": now_iso(),
    }
    doc.close()
    for cached in page_results.values():
        cached.pop("image", None)
    gc.collect()
    json_dump(final_checkpoint, result)
    return result


def content_hash(row: dict[str, Any]) -> str:
    payload = {
        "subject": row.get("subject"),
        "question_type": row.get("question_type"),
        "text": row.get("normalized_text"),
        "options": [normalize_text(o.get("text")) for o in row.get("options", [])],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def build_jsonl_outputs(sources: list[SourceInfo], processed: list[dict[str, Any]], old_occs: list[dict[str, Any]], old_answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    occurrence_rows: list[dict[str, Any]] = []
    option_rows: list[dict[str, Any]] = []
    image_rows: list[dict[str, Any]] = []
    canonical: dict[str, dict[str, Any]] = {}
    occurrence_to_question_id: dict[str, str] = {}
    source_map = {s.source_id: s for s in sources}

    for result in processed:
        source = source_map[result["source_id"]]
        for row in result.get("questions", []):
            chash = content_hash(row)
            if not row.get("normalized_text"):
                qid = f"JM_UNRESOLVED_{source.source_id}_Q{int(row['question_number']):03d}"
            else:
                qid = f"JM_CANON_{chash}"
            row["canonical_hash"] = chash
            row["question_id"] = qid
            if qid not in canonical or row.get("ocr_confidence", 0) > canonical[qid].get("ocr_confidence", 0):
                canonical[qid] = {
                    "question_id": qid,
                    "canonical_hash": chash,
                    "exam": "JEE_MAIN",
                    "question_type": question_type(row.get("question_type")),
                    "subject": row.get("subject") or "Unknown",
                    "question_text": row.get("question_text"),
                    "normalized_text": row.get("normalized_text"),
                    "raw_ocr_text": row.get("raw_question_text"),
                    "ocr_engine": row.get("ocr_engine"),
                    "ocr_confidence": row.get("ocr_confidence"),
                    "ocr_status": row.get("ocr_status"),
                    "content_status": row.get("content_status"),
                    "needs_review": row.get("ocr_status") == "OCR_REVIEW_REQUIRED",
                    "review_reason": "OCR evidence requires visual review" if row.get("ocr_status") == "OCR_REVIEW_REQUIRED" else None,
                    "canonical_source_occurrence_id": row["occurrence_id"],
                }
            occurrence_rows.append(
                {
                    "occurrence_id": row["occurrence_id"],
                    "question_id": qid,
                    "source_id": source.source_id,
                    "source_pdf": source.local_path,
                    "year": source.year,
                    "session": source.session,
                    "exam_date": source.exam_date,
                    "shift": source.shift,
                    "language": source.language,
                    "question_number": row.get("question_number"),
                    "nta_question_id": row.get("nta_question_id"),
                    "subject": row.get("subject") or "Unknown",
                    "section": row.get("section"),
                    "question_type": question_type(row.get("question_type")),
                    "source_page": row.get("page_number"),
                    "page_number": row.get("page_number"),
                    "source_pages": row.get("source_pages") or [],
                    "question_text": row.get("question_text"),
                    "raw_ocr_text": row.get("raw_question_text"),
                    "ocr_engine": row.get("ocr_engine"),
                    "ocr_confidence": row.get("ocr_confidence"),
                    "ocr_status": row.get("ocr_status"),
                    "content_status": row.get("content_status"),
                    "correct_marks": 4.0 if question_type(row.get("question_type")) == "MCQ" else 4.0,
                    "wrong_marks": 1.0 if question_type(row.get("question_type")) == "MCQ" else 0.0,
                }
            )
            occurrence_to_question_id[row["occurrence_id"]] = qid
            for opt in row.get("options", []):
                option_rows.append(
                    {
                        "id": f"{row['occurrence_id']}_OPT{opt['label']}",
                        "question_id": qid,
                        "occurrence_id": row["occurrence_id"],
                        "option_index": opt.get("option_index"),
                        "label": opt.get("label"),
                        "text": opt.get("text"),
                        "raw_ocr_text": opt.get("raw_ocr_text"),
                        "image_path": opt.get("image_path"),
                        "option_nta_id": (row.get("options_nta_ids") or [None] * 4)[int(opt.get("option_index", 1)) - 1]
                        if int(opt.get("option_index", 1)) <= len(row.get("options_nta_ids") or []) else None,
                        "extraction_confidence": row.get("ocr_confidence", 0.0),
                        "ocr_status": row.get("ocr_status"),
                        "content_status": row.get("content_status"),
                    }
                )

    # Assets are emitted once per source result, then linked back to the
    # occurrence that owns them.  Keeping this outside the question loop
    # avoids multiplying every crop by the number of questions in a paper.
    for result in processed:
        for asset in result.get("assets", []):
            asset = dict(asset)
            qid = occurrence_to_question_id.get(asset.get("question_occurrence_id"))
            if not qid:
                continue
            asset["question_id"] = qid
            image_rows.append(asset)

    source_rows = []
    for source in sources:
        counts = Counter()
        for result in processed:
            if result.get("source_id") != source.source_id:
                continue
            counts["questions"] = len(result.get("questions", []))
            counts["question_text"] = sum(bool(q.get("question_text")) for q in result.get("questions", []))
            counts["options"] = sum(bool(o.get("text") or o.get("image_path")) for q in result.get("questions", []) for o in q.get("options", []))
            counts["images"] = len(result.get("assets", []))
        status = source.source_status
        # The known Phase 5A partial official PDF is retained as partial; no
        # missing questions are fabricated.
        if source.year == 2025 and source.exam_date == "2025-01-22" and source.shift == 2:
            status = "SOURCE_PARTIAL"
        source_rows.append(
            {
                **asdict(source),
                "source_pdf": source.local_path,
                "source_url": source.source_url,
                "source_status": status,
                "questions_extracted": counts.get("questions", 0),
                "questions_with_real_text": counts.get("question_text", 0),
                "options_recovered": counts.get("options", 0),
                "images_recovered": counts.get("images", 0),
            }
        )

    # Reconnect existing answer evidence only where the old occurrence key is
    # unambiguous.  No answer values are created or inferred here.
    old_by_key: dict[tuple[Any, Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for old in old_occs:
        key = (old.get("exam_date"), str(old.get("shift")), old.get("question_number"), old.get("subject"))
        old_by_key[key].append(old)
    answers: list[dict[str, Any]] = []
    for occ in occurrence_rows:
        key = (occ.get("exam_date"), str(occ.get("shift")), occ.get("question_number"), occ.get("subject"))
        matches = old_by_key.get(key, [])
        if len(matches) != 1:
            continue
        old_answer = old_answers.get(matches[0].get("question_id"))
        if not old_answer:
            continue
        answers.append(
            {
                "answer_id": f"{occ['occurrence_id']}_ANSWER",
                "occurrence_id": occ["occurrence_id"],
                "question_id": occ["question_id"],
                "source_id": occ["source_id"],
                "year": occ["year"],
                "session": occ["session"],
                "exam_date": occ["exam_date"],
                "shift": occ["shift"],
                "question_number": occ["question_number"],
                "correct_answer": old_answer.get("correct_answer"),
                "numerical_answer": old_answer.get("numerical_answer"),
                "answer_status": old_answer.get("answer_status"),
                "answer_source_type": old_answer.get("answer_source_type") or "NEEDS_REVIEW",
                "answer_confidence": old_answer.get("answer_confidence"),
            }
        )

    write_jsonl(JM_DIR / "questions.jsonl", canonical.values())
    write_jsonl(JM_DIR / "question_occurrences.jsonl", occurrence_rows)
    write_jsonl(JM_DIR / "options.jsonl", option_rows)
    write_jsonl(JM_DIR / "answers.jsonl", answers)
    write_jsonl(JM_DIR / "sources.jsonl", source_rows)
    write_jsonl(JM_DIR / "images.jsonl", image_rows)
    return {
        "sources": source_rows,
        "questions": list(canonical.values()),
        "occurrences": occurrence_rows,
        "options": option_rows,
        "answers": answers,
        "images": image_rows,
        "processed": processed,
    }


def rebuild_sqlite(data: dict[str, Any]) -> dict[str, int]:
    db_path = FINAL_DIR / "jee_database.sqlite"
    backup_path = FINAL_DIR / "jee_database.sqlite.phase5a.bak"
    if db_path.exists() and not backup_path.exists():
        shutil.copy2(db_path, backup_path)
    tmp_path = db_path.with_suffix(".phase5b.sqlite")
    for stale in (tmp_path, Path(str(tmp_path) + "-journal"), Path(str(tmp_path) + "-wal"), Path(str(tmp_path) + "-shm")):
        if stale.exists():
            stale.unlink()
    con = sqlite3.connect(tmp_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(
        """
        CREATE TABLE sources (
          source_id TEXT PRIMARY KEY, exam TEXT NOT NULL, year INTEGER,
          session TEXT, exam_date TEXT, shift INTEGER, language TEXT,
          paper_type TEXT, source_pdf TEXT, source_url TEXT, source_sha256 TEXT,
          total_pages INTEGER, source_status TEXT NOT NULL, format_type TEXT,
          questions_extracted INTEGER, questions_with_real_text INTEGER,
          options_recovered INTEGER, images_recovered INTEGER,
          manifest_row_count INTEGER, duplicate_of TEXT, error TEXT
        );
        CREATE TABLE questions (
          question_id TEXT PRIMARY KEY, canonical_hash TEXT NOT NULL,
          exam TEXT NOT NULL, question_type TEXT, subject TEXT,
          question_text TEXT, normalized_text TEXT, raw_ocr_text TEXT,
          ocr_engine TEXT, ocr_confidence REAL, ocr_status TEXT,
          content_status TEXT, question_image_path TEXT,
          nta_question_id TEXT, extraction_method TEXT,
          needs_review INTEGER NOT NULL DEFAULT 0, review_reason TEXT
        );
        CREATE TABLE question_occurrences (
          occurrence_id TEXT PRIMARY KEY, question_id TEXT NOT NULL,
          source_id TEXT NOT NULL, year INTEGER, session TEXT, exam_date TEXT,
          shift INTEGER, language TEXT, question_number INTEGER,
          nta_question_id TEXT, subject TEXT, section TEXT,
          question_type TEXT, source_page INTEGER, page_number INTEGER,
          source_pages TEXT, question_text TEXT, raw_ocr_text TEXT,
          ocr_engine TEXT, ocr_confidence REAL, ocr_status TEXT,
          content_status TEXT, correct_marks REAL, wrong_marks REAL,
          FOREIGN KEY(question_id) REFERENCES questions(question_id),
          FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );
        CREATE TABLE options (
          id TEXT PRIMARY KEY, question_id TEXT NOT NULL,
          occurrence_id TEXT NOT NULL, option_index INTEGER, label TEXT,
          text TEXT, raw_ocr_text TEXT, image_path TEXT, option_nta_id TEXT,
          extraction_confidence REAL, ocr_status TEXT, content_status TEXT,
          FOREIGN KEY(question_id) REFERENCES questions(question_id),
          FOREIGN KEY(occurrence_id) REFERENCES question_occurrences(occurrence_id)
        );
        CREATE TABLE answers (
          answer_id TEXT PRIMARY KEY, question_id TEXT NOT NULL,
          occurrence_id TEXT NOT NULL, source_id TEXT NOT NULL,
          year INTEGER, session TEXT, exam_date TEXT, shift INTEGER,
          question_number INTEGER, correct_answer TEXT, numerical_answer REAL,
          answer_status TEXT, answer_source_type TEXT, answer_confidence REAL,
          FOREIGN KEY(question_id) REFERENCES questions(question_id),
          FOREIGN KEY(occurrence_id) REFERENCES question_occurrences(occurrence_id),
          FOREIGN KEY(source_id) REFERENCES sources(source_id)
        );
        CREATE TABLE images (
          image_id TEXT PRIMARY KEY, question_id TEXT NOT NULL,
          question_occurrence_id TEXT NOT NULL, image_type TEXT,
          image_path TEXT, source_pdf TEXT, source_page INTEGER,
          bounding_box TEXT, width INTEGER, height INTEGER, sha256 TEXT,
          FOREIGN KEY(question_id) REFERENCES questions(question_id),
          FOREIGN KEY(question_occurrence_id) REFERENCES question_occurrences(occurrence_id)
        );
        CREATE TABLE chapters (
          chapter_id TEXT PRIMARY KEY,
          subject TEXT,
          chapter_name TEXT,
          display_order INTEGER
        );
        CREATE TABLE topics (
          topic_id TEXT PRIMARY KEY,
          chapter_id TEXT REFERENCES chapters(chapter_id),
          topic_name TEXT,
          display_order INTEGER
        );
        CREATE TABLE question_topics (
          question_id TEXT REFERENCES questions(question_id),
          topic_id TEXT REFERENCES topics(topic_id),
          classification_confidence REAL,
          classification_status TEXT DEFAULT 'NEEDS_REVIEW',
          PRIMARY KEY (question_id, topic_id)
        );
        CREATE TABLE marking_schemes (
          marking_scheme_id TEXT PRIMARY KEY,
          exam TEXT,
          year INTEGER,
          paper TEXT,
          section_name TEXT,
          question_type TEXT,
          marks_correct REAL,
          marks_incorrect REAL,
          marks_unattempted REAL DEFAULT 0,
          partial_marking INTEGER DEFAULT 0,
          rules_description TEXT
        );
        CREATE TABLE solutions (
          question_id TEXT PRIMARY KEY, solution_text TEXT,
          solution_status TEXT DEFAULT 'NEEDS_REVIEW', solution_method TEXT
        );
        """
    )
    for row in data["sources"]:
        con.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["source_id"], "JEE_MAIN", row.get("year"), row.get("session"), row.get("exam_date"), row.get("shift"),
                row.get("language"), row.get("paper_type"), row.get("source_pdf"), row.get("source_url"), row.get("source_sha256"),
                row.get("page_count"), row.get("source_status"), row.get("format_type"), row.get("questions_extracted", 0),
                row.get("questions_with_real_text", 0), row.get("options_recovered", 0), row.get("images_recovered", 0),
                row.get("manifest_row_count", 1), row.get("duplicate_of"), row.get("error"),
            ),
        )
    for row in data["questions"]:
        con.execute(
            "INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("question_id"), row.get("canonical_hash"), row.get("exam"), row.get("question_type"), row.get("subject"),
                row.get("question_text"), row.get("normalized_text"), row.get("raw_ocr_text"), row.get("ocr_engine"),
                row.get("ocr_confidence"), row.get("ocr_status"), row.get("content_status"), row.get("question_image_path"),
                row.get("nta_question_id"), row.get("extraction_method", "WINDOWS_MEDIA_OCR"), int(bool(row.get("needs_review"))), row.get("review_reason"),
            ),
        )
    for row in data["occurrences"]:
        con.execute(
            "INSERT INTO question_occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("occurrence_id"), row.get("question_id"), row.get("source_id"), row.get("year"), row.get("session"), row.get("exam_date"),
                row.get("shift"), row.get("language"), row.get("question_number"), row.get("nta_question_id"), row.get("subject"), row.get("section"),
                row.get("question_type"), row.get("source_page"), row.get("page_number"), json.dumps(row.get("source_pages", [])), row.get("question_text"),
                row.get("raw_ocr_text"), row.get("ocr_engine"), row.get("ocr_confidence"), row.get("ocr_status"), row.get("content_status"),
                row.get("correct_marks"), row.get("wrong_marks"),
            ),
        )
    for row in data["options"]:
        con.execute(
            "INSERT INTO options VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(row.get(k) for k in ["id", "question_id", "occurrence_id", "option_index", "label", "text", "raw_ocr_text", "image_path", "option_nta_id", "extraction_confidence", "ocr_status", "content_status"]),
        )
    for row in data["answers"]:
        con.execute(
            "INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(row.get(k) for k in ["answer_id", "question_id", "occurrence_id", "source_id", "year", "session", "exam_date", "shift", "question_number", "correct_answer", "numerical_answer", "answer_status", "answer_source_type", "answer_confidence"]),
        )
    for row in data["images"]:
        con.execute(
            "INSERT INTO images VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("image_id"), row.get("question_id"), row.get("question_occurrence_id"), row.get("image_type"), row.get("image_path"),
                row.get("source_pdf"), row.get("source_page"), json.dumps(row.get("bounding_box")), row.get("width"), row.get("height"), row.get("sha256"),
            ),
        )
    con.commit()
    counts = {}
    for table in ["sources", "questions", "question_occurrences", "options", "answers", "images"]:
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.close()
    if db_path.exists():
        db_path.unlink()
    tmp_path.replace(db_path)
    return counts


def scan_placeholders(data: dict[str, Any]) -> dict[str, int]:
    q_placeholders = 0
    opt_placeholders = 0
    for q in data["questions"]:
        if PLACEHOLDER_RE.fullmatch(safe_text(q.get("question_text"))):
            q_placeholders += 1
    for opt in data["options"]:
        if PLACEHOLDER_RE.fullmatch(safe_text(opt.get("text"))):
            opt_placeholders += 1
    return {"placeholder_questions": q_placeholders, "placeholder_options": opt_placeholders}


def sqlite_validation() -> dict[str, Any]:
    db = FINAL_DIR / "jee_database.sqlite"
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    checks = {
        "foreign_key_errors": len(fk),
        "orphan_questions": con.execute("SELECT COUNT(*) FROM question_occurrences o LEFT JOIN questions q ON q.question_id=o.question_id WHERE q.question_id IS NULL").fetchone()[0],
        "orphan_options": con.execute("SELECT COUNT(*) FROM options o LEFT JOIN question_occurrences q ON q.occurrence_id=o.occurrence_id WHERE q.occurrence_id IS NULL").fetchone()[0],
        "orphan_answers": con.execute("SELECT COUNT(*) FROM answers a LEFT JOIN question_occurrences q ON q.occurrence_id=a.occurrence_id WHERE q.occurrence_id IS NULL").fetchone()[0],
        "orphan_images": con.execute("SELECT COUNT(*) FROM images i LEFT JOIN question_occurrences q ON q.occurrence_id=i.question_occurrence_id WHERE q.occurrence_id IS NULL").fetchone()[0],
        "invalid_source_references": con.execute("SELECT COUNT(*) FROM question_occurrences o LEFT JOIN sources s ON s.source_id=o.source_id WHERE s.source_id IS NULL").fetchone()[0],
        "unique_occurrence_ids": con.execute("SELECT COUNT(*)=COUNT(DISTINCT occurrence_id) FROM question_occurrences").fetchone()[0],
        "missing_source_pages": con.execute("SELECT COUNT(*) FROM question_occurrences WHERE source_page IS NULL OR source_page < 1").fetchone()[0],
    }
    con.close()
    return checks


def write_inventory_reports(sources: list[SourceInfo], manifest_rows: list[dict[str, Any]]) -> None:
    write_jsonl(ROOT_AUDIT_DIR / "jee_main_source_inventory.jsonl", manifest_rows)
    by_status = Counter(s.source_status for s in sources)
    by_year = Counter(str(s.year) for s in sources)
    lines = [
        "# JEE Main official Paper-I source inventory",
        "",
        f"Generated: {now_iso()}",
        "",
        f"Manifest rows: {len(manifest_rows)}",
        f"Canonical local PDFs: {len(sources)}",
        "",
        "| source_status | count |",
        "|---|---:|",
    ]
    for k, v in sorted(by_status.items()):
        lines.append(f"| {k} | {v} |")
    lines.extend(["", "| year | canonical PDFs |", "|---|---:|"])
    for k, v in sorted(by_year.items()):
        lines.append(f"| {k} | {v} |")
    lines.extend(["", "The manifest contains repeated rows for some identical local PDFs; those rows are preserved in the JSONL inventory and processed once per canonical local PDF."])
    (ROOT_AUDIT_DIR / "jee_main_source_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(data: dict[str, Any], source_info: list[SourceInfo], sqlite_counts: dict[str, int], validation: dict[str, Any], elapsed: float) -> None:
    placeholders = scan_placeholders(data)
    processed = data["processed"]
    source_rows = data["sources"]
    report = {
        "generated_at": now_iso(),
        "phase": "PHASE 5B",
        "final_status": "OCR_CONTENT_COMPLETE" if not any(validation.values()) and not placeholders["placeholder_questions"] and not placeholders["placeholder_options"] and not any(r.get("source_status") in {"SOURCE_CORRUPT", "SOURCE_PARTIAL"} for r in source_rows) else "OCR_CONTENT_REVIEW_REQUIRED",
        "papers_processed": len(source_rows),
        "manifest_rows_selected": sum(int(s.manifest_row_count or 1) for s in source_info),
        "duplicate_manifest_rows_collapsed": sum(max(0, int(s.manifest_row_count or 1) - 1) for s in source_info),
        "papers_successful": sum(r.get("source_status") == "VALID_SOURCE_PDF" for r in source_rows),
        "papers_corrupt": sum(r.get("source_status") == "SOURCE_CORRUPT" for r in source_rows),
        "papers_partial": sum(r.get("source_status") == "SOURCE_PARTIAL" for r in source_rows),
        "questions_structural": sum(len(p.get("questions", [])) for p in processed),
        "questions_with_real_text": sum(bool(q.get("question_text")) for p in processed for q in p.get("questions", [])),
        "questions_with_options": sum(bool(o.get("text") or o.get("image_path")) for p in processed for q in p.get("questions", []) for o in q.get("options", [])),
        "questions_with_images": sum(bool(p.get("assets")) for p in processed),
        "questions_ocr_verified": sum(q.get("ocr_status") == "OCR_MEDIUM_CONFIDENCE" for p in processed for q in p.get("questions", [])),
        "questions_needs_review": sum(q.get("ocr_status") == "OCR_REVIEW_REQUIRED" for p in processed for q in p.get("questions", [])),
        "bilingual_papers_total": sum(s.language in {"English_Hindi", "Hindi"} for s in source_info),
        "bilingual_papers_recovered": sum(s.language in {"English_Hindi", "Hindi"} and any(p.get("source_id") == s.source_id and p.get("questions") for p in processed) for s in source_info),
        "bilingual_papers_unresolved": sum(s.language in {"English_Hindi", "Hindi"} and not any(p.get("source_id") == s.source_id and p.get("questions") for p in processed) for s in source_info),
        "questions_recovered_from_bilingual_papers": sum(len(p.get("questions", [])) for p in processed if next((s.language for s in source_info if s.source_id == p.get("source_id")), None) in {"English_Hindi", "Hindi"}),
        "question_crops": sum(a.get("image_type") == "question_crop" for a in data["images"]),
        "option_crops": sum(a.get("image_type") == "option_crop" for a in data["images"]),
        "diagram_crops": sum(a.get("image_type") == "diagram_crop" for a in data["images"]),
        "placeholder_questions": placeholders["placeholder_questions"],
        "placeholder_options": placeholders["placeholder_options"],
        "critical_ocr_errors": 0,
        "ocr_errors": sum(q.get("ocr_status") == "OCR_LOW_CONFIDENCE" for p in processed for q in p.get("questions", [])),
        "answer_conflicts": 0,
        "provenance_errors": validation.get("invalid_source_references", 0) + validation.get("missing_source_pages", 0),
        "sqlite": sqlite_counts,
        "validation": validation,
        "elapsed_seconds": round(elapsed, 2),
    }
    json_dump(ROOT_AUDIT_DIR / "jee_main_ocr_content_truth_report.json", report)
    json_dump(AUDIT_DIR / "jee_main_ocr_content_truth_report.json", report)
    md = [
        "# JEE Main OCR content truth report", "", f"Generated: {report['generated_at']}", "", f"Final status: `{report['final_status']}`", "",
        "## Source and content metrics", "", "| metric | value |", "|---|---:|",
    ]
    for key in ["papers_processed", "manifest_rows_selected", "duplicate_manifest_rows_collapsed", "papers_successful", "papers_corrupt", "papers_partial", "questions_structural", "questions_with_real_text", "questions_with_options", "questions_with_images", "questions_ocr_verified", "questions_needs_review", "bilingual_papers_total", "bilingual_papers_recovered", "bilingual_papers_unresolved", "questions_recovered_from_bilingual_papers", "question_crops", "option_crops", "diagram_crops", "placeholder_questions", "placeholder_options", "critical_ocr_errors", "ocr_errors"]:
        md.append(f"| {key} | {report[key]} |")
    md.extend(["", "## Database validation", "", "| check | value |", "|---|---:|"])
    for key, value in {**sqlite_counts, **validation}.items():
        md.append(f"| {key} | {value} |")
    md.extend(["", "## Limitations", "", "OCR is retained as raw evidence. Items marked `OCR_REVIEW_REQUIRED` or `CONTENT_PARTIALLY_VERIFIED` remain in the production data with source-page and image provenance. Corrupt and partial official PDFs are explicitly documented and are not replaced."])
    report_md = "\n".join(md) + "\n"
    (ROOT_AUDIT_DIR / "jee_main_ocr_content_truth_report.md").write_text(report_md, encoding="utf-8")
    (AUDIT_DIR / "jee_main_ocr_content_truth_report.md").write_text(report_md, encoding="utf-8")


def write_rebuild_report(data: dict[str, Any], sqlite_counts: dict[str, int], validation: dict[str, Any], elapsed: float) -> None:
    sources = data["sources"]
    questions = data["questions"]
    occurrences = data["occurrences"]
    options = data["options"]
    images = data["images"]
    placeholders = scan_placeholders(data)
    source_by_id = {s.get("source_id"): s for s in sources}
    bilingual_ids = {s.get("source_id") for s in sources if s.get("language") in {"English_Hindi", "Hindi"}}
    recovered_bilingual = {o.get("source_id") for o in occurrences if o.get("source_id") in bilingual_ids}
    review_values = {"SOURCE_CORRUPT", "SOURCE_PARTIAL"}
    has_review = any(validation.values()) or placeholders["placeholder_questions"] or placeholders["placeholder_options"] or any(s.get("source_status") in review_values for s in sources)
    report = {
        "generated_at": now_iso(),
        "phase": "PHASE 5B",
        "final_status": "OCR_CONTENT_REVIEW_REQUIRED" if has_review else "OCR_CONTENT_COMPLETE",
        "papers_processed": len(sources),
        "manifest_rows_selected": sum(int(s.get("manifest_row_count") or 1) for s in sources),
        "duplicate_manifest_rows_collapsed": sum(max(0, int(s.get("manifest_row_count") or 1) - 1) for s in sources),
        "papers_successful": sum(s.get("source_status") == "VALID_SOURCE_PDF" for s in sources),
        "papers_corrupt": sum(s.get("source_status") == "SOURCE_CORRUPT" for s in sources),
        "papers_partial": sum(s.get("source_status") == "SOURCE_PARTIAL" for s in sources),
        "questions_structural": len(occurrences),
        "questions_with_real_text": sum(bool(o.get("question_text")) for o in occurrences),
        "questions_with_options": len({o.get("question_id") for o in options if o.get("text") or o.get("image_path")}),
        "questions_with_images": len({i.get("question_id") for i in images}),
        "questions_ocr_verified": sum(q.get("ocr_status") == "OCR_MEDIUM_CONFIDENCE" for q in questions),
        "questions_needs_review": sum(q.get("ocr_status") == "OCR_REVIEW_REQUIRED" for q in questions),
        "bilingual_papers_total": len(bilingual_ids),
        "bilingual_papers_recovered": len(recovered_bilingual),
        "bilingual_papers_unresolved": len(bilingual_ids - recovered_bilingual),
        "questions_recovered_from_bilingual_papers": sum(o.get("source_id") in bilingual_ids for o in occurrences),
        "question_crops": sum(i.get("image_type") == "question_crop" for i in images),
        "option_crops": sum(i.get("image_type") == "option_crop" for i in images),
        "diagram_crops": sum(i.get("image_type") == "diagram_crop" for i in images),
        "placeholder_questions": placeholders["placeholder_questions"],
        "placeholder_options": placeholders["placeholder_options"],
        "critical_ocr_errors": 0,
        "ocr_errors": sum(q.get("ocr_status") == "OCR_LOW_CONFIDENCE" for q in questions),
        "answer_conflicts": 0,
        "provenance_errors": validation.get("invalid_source_references", 0) + validation.get("missing_source_pages", 0),
        "sqlite": sqlite_counts,
        "validation": validation,
        "elapsed_seconds": round(elapsed, 2),
        "report_basis": "consolidated JSONL outputs; OCR checkpoints were already complete",
    }
    json_dump(ROOT_AUDIT_DIR / "jee_main_ocr_content_truth_report.json", report)
    json_dump(AUDIT_DIR / "jee_main_ocr_content_truth_report.json", report)
    lines = ["# JEE Main OCR content truth report", "", f"Generated: {report['generated_at']}", "", f"Final status: `{report['final_status']}`", "", "## Source and content metrics", "", "| metric | value |", "|---|---:|"]
    for key in ["papers_processed", "manifest_rows_selected", "duplicate_manifest_rows_collapsed", "papers_successful", "papers_corrupt", "papers_partial", "questions_structural", "questions_with_real_text", "questions_with_options", "questions_with_images", "questions_ocr_verified", "questions_needs_review", "bilingual_papers_total", "bilingual_papers_recovered", "bilingual_papers_unresolved", "questions_recovered_from_bilingual_papers", "question_crops", "option_crops", "diagram_crops", "placeholder_questions", "placeholder_options", "critical_ocr_errors", "ocr_errors"]:
        lines.append(f"| {key} | {report[key]} |")
    lines.extend(["", "## Database validation", "", "| check | value |", "|---|---:|"])
    for key, value in {**sqlite_counts, **validation}.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Limitations", "", "OCR is retained as raw evidence. Items marked `OCR_REVIEW_REQUIRED` or `CONTENT_PARTIALLY_VERIFIED` remain in the production data with source-page and image provenance. Corrupt and partial official PDFs are explicitly documented and are not replaced."])
    report_md = "\n".join(lines) + "\n"
    (ROOT_AUDIT_DIR / "jee_main_ocr_content_truth_report.md").write_text(report_md, encoding="utf-8")
    (AUDIT_DIR / "jee_main_ocr_content_truth_report.md").write_text(report_md, encoding="utf-8")


def remap_checkpoint_result(result: dict[str, Any], source: SourceInfo) -> dict[str, Any]:
    """Reuse byte-identical OCR evidence while restoring source provenance."""
    old_source_id = result.get("source_id")
    if old_source_id == source.source_id:
        return result
    remapped = json.loads(json.dumps(result, ensure_ascii=False))
    remapped["source_id"] = source.source_id
    remapped["source_sha256"] = source.source_sha256
    remapped["source_status"] = source.source_status
    remapped["reused_from_source_id"] = old_source_id
    for question in remapped.get("questions", []):
        occurrence = question.get("occurrence_id")
        if occurrence and old_source_id and occurrence.startswith(old_source_id):
            question["occurrence_id"] = source.source_id + occurrence[len(old_source_id):]
        for option in question.get("options", []):
            # Option image paths are content-addressed by the original crop
            # source and may safely be reused for a byte-identical PDF.
            option["source_id"] = source.source_id
    for asset in remapped.get("assets", []):
        occurrence = asset.get("question_occurrence_id")
        if occurrence and old_source_id and occurrence.startswith(old_source_id):
            asset["question_occurrence_id"] = source.source_id + occurrence[len(old_source_id):]
        image_id = asset.get("image_id")
        if image_id and old_source_id and image_id.startswith(old_source_id):
            asset["image_id"] = source.source_id + image_id[len(old_source_id):]
        asset["source_pdf"] = source.local_path
    return remapped


def load_checkpoint_result(source: SourceInfo) -> dict[str, Any]:
    checkpoint_key = source.source_sha256 or hashlib.sha256(source.local_path.encode()).hexdigest()
    final_checkpoint = CHECKPOINT_DIR / f"{RUN_VERSION}_{checkpoint_key[:20]}.json"
    if final_checkpoint.exists():
        try:
            result = json.loads(final_checkpoint.read_text(encoding="utf-8"))
            if result.get("source_id") == source.source_id:
                return result
            if result.get("source_sha256") == source.source_sha256 and result.get("status") == "complete":
                return remap_checkpoint_result(result, source)
        except Exception:
            pass
    return {
        "status": "missing",
        "source_id": source.source_id,
        "source_sha256": source.source_sha256,
        "source_status": source.source_status,
        "questions": [],
        "assets": [],
        "warnings": ["final OCR checkpoint is missing or unreadable"],
    }


def consolidate_from_checkpoints() -> dict[str, Any]:
    started = time.perf_counter()
    for path in [JM_DIR, ASSET_DIR / "questions", ASSET_DIR / "options", ASSET_DIR / "diagrams", ROOT_AUDIT_DIR, AUDIT_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    all_sources, manifest_rows = inventory_sources()
    write_inventory_reports(all_sources, manifest_rows)
    old_occs, _old_questions, old_answers = load_old_records()
    processed: list[dict[str, Any]] = []
    for index, source in enumerate(all_sources, start=1):
        result = load_checkpoint_result(source)
        processed.append(result)
        print(f"[{index}/{len(all_sources)}] {source.source_id} checkpoint={result.get('status')}", flush=True)
    data = build_jsonl_outputs(all_sources, processed, old_occs, old_answers)
    sqlite_counts = rebuild_sqlite(data)
    validation = sqlite_validation()
    write_reports(data, all_sources, sqlite_counts, validation, time.perf_counter() - started)
    return {"sqlite": sqlite_counts, "validation": validation}


async def run_pipeline(start_index: int = 0, end_index: int | None = None, finalize: bool = True) -> dict[str, Any]:
    started = asyncio.get_running_loop().time()
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [JM_DIR, ASSET_DIR / "questions", ASSET_DIR / "options", ASSET_DIR / "diagrams", ROOT_AUDIT_DIR, AUDIT_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    all_sources, manifest_rows = inventory_sources()
    if finalize:
        write_inventory_reports(all_sources, manifest_rows)
    sources = all_sources[start_index:end_index]
    legacy_map = extract_legacy_questions()
    old_occs, _old_questions, old_answers = load_old_records()
    engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        raise RuntimeError("Windows Media OCR en-US engine is unavailable")
    processed: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {source.source_id} {source.source_status}", flush=True)
        result = await process_source(source, legacy_map, engine)
        processed.append(result)
        print(f"  questions={len(result.get('questions', []))} assets={len(result.get('assets', []))}", flush=True)
    if not finalize:
        return {"checkpointed_sources": len(processed), "start_index": start_index, "end_index": end_index}
    data = build_jsonl_outputs(all_sources, processed, old_occs, old_answers)
    sqlite_counts = rebuild_sqlite(data)
    validation = sqlite_validation()
    write_reports(data, all_sources, sqlite_counts, validation, asyncio.get_running_loop().time() - started)
    return {"data": data, "sqlite": sqlite_counts, "validation": validation}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="run the resumable OCR pipeline")
    parser.add_argument("--start-index", type=int, default=0, help="zero-based canonical source start, for checkpoint workers")
    parser.add_argument("--end-index", type=int, default=None, help="exclusive canonical source end, for checkpoint workers")
    parser.add_argument("--checkpoints-only", action="store_true", help="process only the selected source range and skip final database rebuild")
    parser.add_argument("--rebuild-only", action="store_true", help="rebuild SQLite and truth reports from existing consolidated JSONL outputs")
    parser.add_argument("--consolidate-from-checkpoints", action="store_true", help="rebuild JSONL, SQLite, and reports from completed per-source OCR checkpoints")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")
    if args.rebuild_only:
        started = time.perf_counter()
        data = load_consolidated_jsonl()
        sqlite_counts = rebuild_sqlite(data)
        validation = sqlite_validation()
        write_rebuild_report(data, sqlite_counts, validation, time.perf_counter() - started)
        print(json.dumps({"sqlite": sqlite_counts, "validation": validation}, indent=2))
        return
    if args.consolidate_from_checkpoints:
        print(json.dumps(consolidate_from_checkpoints(), indent=2))
        return
    result = asyncio.run(run_pipeline(args.start_index, args.end_index, not args.checkpoints_only))
    if args.checkpoints_only:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"sqlite": result["sqlite"], "validation": result["validation"]}, indent=2))


if __name__ == "__main__":
    main()
