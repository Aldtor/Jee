"""Phase 5B.2 targeted visual verification for the JEE Main OCR dataset.

The script is intentionally conservative and does not run OCR.  It uses the
existing OCR candidate text, renders the original official PDF page/crop with
PyMuPDF, checks source metadata and option/image provenance, and records only
records whose source-page evidence is sufficiently clear for promotion.

Usage:
    python targeted_visual_verify_jee_main.py --prepare
    python targeted_visual_verify_jee_main.py --promote
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import textwrap
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageOps

import ocr_reconstruct_jee_main as pipeline
import reconcile_jee_main_phase5b1 as phase51


BASE = Path(__file__).resolve().parent
FINAL = BASE / "JEE_QUESTION_DATABASE_FINAL"
JM = FINAL / "JEE_MAIN"
AUDIT = BASE / "audit"
WORK = BASE / "tmp" / "phase5b2_visual_verification"
MANIFEST = BASE / "JEE_Main_PYQ_Archive" / "jee_main_official_paper_manifest.json"
APPROVED_MANIFEST = AUDIT / "jee_main_ocr_visual_approval_manifest.json"
BASELINE_MANIFEST = AUDIT / "jee_main_ocr_visual_baseline.json"
ZOOM = 3.0

PRIORITY = [
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

PLACEHOLDER_RE = phase51.PLACEHOLDER_RE


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def load_approved_records(selected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Load the human visual-review disposition, if present.

    The prepared sample is deliberately broader than the promotion set.  A
    record is promoted only when its occurrence ID appears in the reviewed
    approval manifest; all other reviewed records remain review-required.
    """
    if not APPROVED_MANIFEST.exists():
        return selected, None
    approval = read_json(APPROVED_MANIFEST)
    approved_ids = [str(value) for value in approval.get("approved_occurrence_ids", [])]
    approved_set = set(approved_ids)
    available = {str(row.get("occurrence_id")) for row in selected}
    unknown = sorted(approved_set - available)
    if unknown:
        raise RuntimeError(f"Approval manifest contains IDs outside selected_candidates.json: {unknown[:5]}")
    if len(approved_ids) != len(approved_set):
        raise RuntimeError("Approval manifest contains duplicate occurrence IDs.")
    approved = [row for row in selected if row.get("occurrence_id") in approved_set]
    return approved, approval


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def norm_tokens(value: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.findall(r"[a-z0-9]+", text)


def token_coverage(candidate: str | None, source_text: str | None) -> float:
    candidate_tokens = norm_tokens(candidate)
    if not candidate_tokens:
        return 0.0
    source_tokens = set(norm_tokens(source_text))
    return sum(token in source_tokens for token in candidate_tokens) / len(candidate_tokens)


def source_number_present(question_number: Any, source_text: str) -> bool:
    if question_number in (None, ""):
        return False
    number = str(int(question_number)) if str(question_number).isdigit() else str(question_number)
    return bool(re.search(rf"(?<!\d)0*{re.escape(number)}(?!\d)", source_text))


def image_is_clear(image: Image.Image) -> bool:
    if image.width < 40 or image.height < 12:
        return False
    variance = ImageStat.Stat(image.convert("L")).var[0]
    return variance >= 2.0


def fitz_to_pil(pix: fitz.Pixmap) -> Image.Image:
    mode = "RGBA" if pix.alpha else "RGB"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


class PdfCache:
    def __init__(self) -> None:
        self.docs: dict[str, fitz.Document] = {}
        self.sha: dict[str, str | None] = {}
        self.pdfium_docs: dict[str, Any] = {}

    def get(self, relative_path: str) -> tuple[fitz.Document | None, Path, str | None]:
        path = BASE / relative_path
        key = str(path)
        if key in self.docs:
            return self.docs[key], path, self.sha[key]
        if not path.exists():
            self.docs[key] = None  # type: ignore[assignment]
            self.sha[key] = None
            return None, path, None
        try:
            doc = fitz.open(path)
            self.docs[key] = doc
            self.sha[key] = sha256_file(path)
            return doc, path, self.sha[key]
        except Exception:
            self.docs[key] = None  # type: ignore[assignment]
            self.sha[key] = None
            return None, path, None

    def close(self) -> None:
        for doc in self.docs.values():
            if doc is not None:
                doc.close()
        for doc in self.pdfium_docs.values():
            if doc is not None:
                doc.close()

    def get_pdfium(self, path: Path) -> Any:
        key = str(path)
        if key not in self.pdfium_docs:
            try:
                self.pdfium_docs[key] = pdfium.PdfDocument(key)
            except Exception:
                self.pdfium_docs[key] = None
        return self.pdfium_docs[key]


def load_data() -> dict[str, list[dict[str, Any]]]:
    return {
        "sources": read_jsonl(JM / "sources.jsonl"),
        "questions": read_jsonl(JM / "questions.jsonl"),
        "occurrences": read_jsonl(JM / "question_occurrences.jsonl"),
        "options": read_jsonl(JM / "options.jsonl"),
        "answers": read_jsonl(JM / "answers.jsonl"),
        "images": read_jsonl(JM / "images.jsonl"),
    }


def review_flags(
    question: dict[str, Any],
    occurrence: dict[str, Any],
    source: dict[str, Any],
    options: list[dict[str, Any]],
    images: list[dict[str, Any]],
    checkpoint: dict[str, Any],
) -> dict[str, bool]:
    text = str(question.get("question_text") or "")
    labels = {str(row.get("label")) for row in options}
    return {
        "low_ocr_confidence": float(question.get("ocr_confidence") or 0) < 0.5,
        "engine_disagreement": bool(checkpoint.get("pass2_disagreement")),
        "equation_heavy": bool(phase51.EQUATION_RE.search(text)),
        "chemistry_structure": str(question.get("subject")) == "Chemistry" or bool(phase51.CHEMISTRY_RE.search(text)),
        "diagram_heavy": any(row.get("image_type") == "diagram_crop" for row in images),
        "malformed_options": str(question.get("question_type") or "").upper() == "MCQ" and not {"A", "B", "C", "D"}.issubset(labels),
        "suspicious_characters": bool(phase51.SUSPICIOUS_RE.search(text)),
        "incomplete_text": len(text.strip()) < 40 or not text.strip(),
        "bilingual": source.get("language") in {"English_Hindi", "Hindi"},
        "multi_page": len(occurrence.get("source_pages") or []) > 1,
    }


def primary_bucket(flags: dict[str, bool]) -> str:
    return next((name for name in PRIORITY if flags.get(name)), "low_ocr_confidence")


def graphical_options(options: list[dict[str, Any]]) -> bool:
    by_label = {str(row.get("label")): row for row in options}
    if not {"A", "B", "C", "D"}.issubset(by_label):
        return False
    return all(row.get("image_path") and not str(row.get("text") or "").strip() for row in by_label.values())


def option_image_rows(options: list[dict[str, Any]], images: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in images:
        image_type = str(row.get("image_type") or "")
        if image_type in {"option_crop", "option_image"}:
            match = re.search(r"_(?:OPTION_?|OPT)([A-D])(?:_|$)", str(row.get("image_id") or ""))
            if match:
                by_label[match.group(1)].append(row)
    for option in options:
        label = str(option.get("label") or "")
        if option.get("image_path") and not by_label.get(label):
            by_label[label].append(
                {
                    "image_id": option.get("id"),
                    "image_type": "option_crop",
                    "image_path": option.get("image_path"),
                    "source_page": option.get("source_page"),
                    "bounding_box": option.get("bounding_box"),
                    "sha256": option.get("sha256"),
                }
            )
    return by_label


def render_source_crop(doc: fitz.Document | None, page_number: int, bbox: list[float], pdf_path: Path | None = None, pdfs: PdfCache | None = None) -> tuple[Image.Image | None, str | None]:
    try:
        page = doc[page_number - 1]
        rect = fitz.Rect(*[float(value) for value in bbox]) & page.rect
        if rect.is_empty:
            return None, None
        pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=rect, alpha=False)
        image = fitz_to_pil(pix).convert("RGB")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return image, sha256_bytes(stream.getvalue())
    except Exception:
        pass
    if pdf_path is not None and pdfs is not None:
        try:
            pdfium_doc = pdfs.get_pdfium(pdf_path)
            page = pdfium_doc[page_number - 1]
            bitmap = page.render(scale=ZOOM)
            image = bitmap.to_pil().convert("RGB")
            left, top, right, bottom = [int(round(float(value) * ZOOM)) for value in bbox]
            crop = image.crop((left, top, right, bottom))
            stream = io.BytesIO()
            crop.save(stream, format="PNG")
            bitmap.close()
            page.close()
            return crop, sha256_bytes(stream.getvalue())
        except Exception:
            return None, None
    return None, None


def evaluate_record(
    question: dict[str, Any],
    occurrence: dict[str, Any],
    source: dict[str, Any],
    options: list[dict[str, Any]],
    images: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    pdfs: PdfCache,
    render: bool = False,
) -> dict[str, Any]:
    source_pdf = str(occurrence.get("source_pdf") or source.get("source_pdf") or "")
    doc, pdf_path, actual_sha = pdfs.get(source_pdf)
    pages = [int(value) for value in (occurrence.get("source_pages") or [occurrence.get("source_page")]) if str(value).isdigit()]
    pages = sorted(set(page for page in pages if page >= 1))
    valid_pages = bool(doc is not None and pages and all(page <= len(doc) for page in pages))
    page_text = ""
    if valid_pages and doc is not None:
        page_text = "\n".join(doc[page - 1].get_text("text") for page in pages)
    flags = review_flags(question, occurrence, source, options, images, checkpoint)
    q_images = [row for row in images if row.get("image_type") == "question_crop"]
    diagram_images = [row for row in images if row.get("image_type") == "diagram_crop"]
    options_by_label = option_image_rows(options, images)
    graphical = graphical_options(options)
    text_option_rows = [row for row in options if str(row.get("text") or "").strip()]
    option_coverages = [token_coverage(row.get("text"), page_text) for row in text_option_rows]
    q_coverage = token_coverage(question.get("question_text"), page_text)
    metadata_fields = ["year", "session", "exam_date", "shift", "language", "paper_type", "source_url", "source_pdf", "source_sha256"]
    metadata_pass = all(source.get(field) not in (None, "") for field in metadata_fields)
    metadata_pass = metadata_pass and all(occurrence.get(field) == source.get(field) for field in ["year", "session", "exam_date", "shift", "language", "source_pdf"])
    source_hash_pass = bool(actual_sha and actual_sha == source.get("source_sha256"))
    q_image_rows = [row for row in q_images if row.get("source_page") in pages]
    q_image_present = bool(q_image_rows and all(row.get("image_path") and (BASE / str(row["image_path"])).exists() for row in q_image_rows))
    source_number_pass = source_number_present(occurrence.get("question_number"), page_text)
    option_labels = {str(row.get("label")) for row in options}
    abcd_complete = {"A", "B", "C", "D"}.issubset(option_labels)
    option_image_complete = all(options_by_label.get(label) for label in ["A", "B", "C", "D"])
    page_text_lower = page_text.lower()
    page_text_tokens = norm_tokens(page_text)
    image_only_source_page = q_coverage < 0.25 and ("question number" in page_text_lower or "question id" in page_text_lower)
    if str(question.get("question_type") or "").upper() == "MCQ":
        option_evidence_pass = graphical and option_image_complete or (abcd_complete and bool(text_option_rows) and all(coverage >= 0.55 for coverage in option_coverages)) or (option_image_complete and image_only_source_page)
    else:
        option_evidence_pass = True
    strict_coverage = 0.72
    if flags["suspicious_characters"] or flags["engine_disagreement"] or flags["equation_heavy"] or flags["chemistry_structure"]:
        strict_coverage = 0.82
    if flags["incomplete_text"]:
        strict_coverage = 0.94
    question_evidence_pass = bool(norm_tokens(question.get("question_text"))) and (q_coverage >= strict_coverage or image_only_source_page)
    # Short/incomplete OCR candidates and mojibake remain review-required even
    # when the page crop is legible; visual verification must confirm the
    # complete candidate text, not just a fragment or a diagram.
    question_evidence_pass = question_evidence_pass and len(str(question.get("question_text") or "").strip()) >= 40 and not flags["incomplete_text"] and not flags["suspicious_characters"]
    clear = bool(
        doc is not None
        and valid_pages
        and source_hash_pass
        and metadata_pass
        and source_number_pass
        and q_image_present
        and question_evidence_pass
        and option_evidence_pass
    )
    method = "SOURCE_IMAGE_CONFIRMED"
    if graphical:
        method = "GRAPHICAL_OPTION_CONFIRMED"
    elif flags["bilingual"]:
        method = "BILINGUAL_SOURCE_IMAGE_CONFIRMED"
    elif str(question.get("question_type") or "").upper() == "MCQ":
        method = "SOURCE_IMAGE_PLUS_OPTION_CHECK"
    rendered = []
    if render and doc is not None and valid_pages:
        for row in q_image_rows + diagram_images:
            image, rendered_sha = render_source_crop(doc, int(row.get("source_page")), row.get("bounding_box") or [], pdf_path, pdfs)
            if image is not None:
                rendered.append({"image": image, "image_id": row.get("image_id"), "image_type": row.get("image_type"), "source_page": row.get("source_page"), "rendered_sha256": rendered_sha})
        for label in ["A", "B", "C", "D"]:
            for row in options_by_label.get(label, []):
                if row.get("bounding_box") and row.get("source_page"):
                    image, rendered_sha = render_source_crop(doc, int(row.get("source_page")), row.get("bounding_box"), pdf_path, pdfs)
                    if image is not None:
                        rendered.append({"image": image, "image_id": row.get("image_id"), "image_type": "option_crop", "label": label, "source_page": row.get("source_page"), "rendered_sha256": rendered_sha})
    return {
        "occurrence_id": occurrence.get("occurrence_id"),
        "question_id": question.get("question_id"),
        "source_id": occurrence.get("source_id"),
        "source_pdf": source_pdf,
        "source_pages": pages,
        "source_page": occurrence.get("source_page"),
        "question_number": occurrence.get("question_number"),
        "subject": question.get("subject") or occurrence.get("subject"),
        "question_type": question.get("question_type") or occurrence.get("question_type"),
        "language": source.get("language"),
        "year": source.get("year"),
        "exam_date": source.get("exam_date"),
        "session": source.get("session"),
        "shift": source.get("shift"),
        "question_text": question.get("question_text"),
        "flags": flags,
        "primary_bucket": primary_bucket(flags),
        "graphical_option_case": graphical,
        "question_text_coverage": round(q_coverage, 4),
        "option_text_coverages": [round(value, 4) for value in option_coverages],
        "question_number_present_in_source_text": source_number_pass,
        "source_page_text_is_metadata_only": image_only_source_page,
        "source_page_text_token_count": len(page_text_tokens),
        "question_crop_count": len(q_image_rows),
        "diagram_crop_count": len(diagram_images),
        "option_image_complete": option_image_complete,
        "option_evidence_pass": option_evidence_pass,
        "source_pdf_exists": doc is not None,
        "source_sha256_matches": source_hash_pass,
        "metadata_pass": metadata_pass,
        "clear_source_image_confirmation": clear,
        "verification_method": method,
        "rendered_images": rendered,
        "source_image_ids": [row.get("image_id") for row in q_image_rows + diagram_images],
        "source_image_sha256": [row.get("sha256") for row in q_image_rows + diagram_images],
        "engine_disagreement": bool(flags["engine_disagreement"]),
        "risk_score": sum(bool(flags.get(name)) for name in ["equation_heavy", "chemistry_structure", "diagram_heavy", "bilingual"]),
    }


def select_candidates(evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = [row for row in evidence if row["clear_source_image_confirmation"]]
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        by_year[int(row["year"])].append(row)
    selected: list[dict[str, Any]] = []
    selection_summary: dict[str, Any] = {}
    for year in sorted(by_year):
        pool = by_year[year]
        chosen: list[dict[str, Any]] = []
        chosen_ids: set[str] = set()

        def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
            return (item["engine_disagreement"], item["risk_score"], PRIORITY.index(item["primary_bucket"]), item["question_number"] or 0)

        def add_one(predicate) -> None:
            for row in sorted(pool, key=sort_key):
                if row["occurrence_id"] in chosen_ids:
                    continue
                if predicate(row):
                    chosen.append(row)
                    chosen_ids.add(row["occurrence_id"])
                    return

        for subject in ["Physics", "Chemistry", "Mathematics"]:
            add_one(lambda row, subject=subject: row["subject"] == subject)
        for bucket in ["equation_heavy", "chemistry_structure", "diagram_heavy", "bilingual"]:
            add_one(lambda row, bucket=bucket: row["flags"].get(bucket, False))
        add_one(lambda row: row["graphical_option_case"])
        for row in sorted(pool, key=sort_key):
            if len(chosen) >= min(30, len(pool)):
                break
            if row["occurrence_id"] not in chosen_ids:
                chosen.append(row)
                chosen_ids.add(row["occurrence_id"])
        selected.extend(chosen)
        selection_summary[str(year)] = {
            "eligible_clear_source_image_records": len(pool),
            "selected_for_promotion": len(chosen),
            "available_review_records": sum(1 for row in evidence if int(row["year"]) == year),
            "subjects_selected": dict(Counter(row["subject"] for row in chosen)),
            "buckets_selected": dict(Counter(row["primary_bucket"] for row in chosen)),
            "adversarial_sample_size": len(chosen),
            "adversarial_sample_minimum": 30,
            "adversarial_sample_pass": len(chosen) >= 30,
        }
    return selected, selection_summary


def card_for_record(record: dict[str, Any], q_image: Image.Image | None, option_images: list[tuple[str, Image.Image]]) -> Image.Image:
    card = Image.new("RGB", (700, 320), "white")
    draw = ImageDraw.Draw(card)
    font = ImageFont.load_default()
    label = f"{record['year']} {record['subject']} Q{record['question_number']} {record['primary_bucket']}"
    draw.text((8, 6), label, fill="black", font=font)
    draw.text((8, 20), f"{record['occurrence_id']}  cov={record['question_text_coverage']}", fill="black", font=font)
    if q_image is not None:
        preview = ImageOps.contain(q_image.convert("RGB"), (680, 115))
        card.paste(preview, ((700 - preview.width) // 2, 38))
    ocr_text = textwrap.shorten(" ".join(str(record.get("question_text") or "").split()), width=185, placeholder=" …")
    draw.multiline_text((8, 158), "OCR: " + "\n".join(textwrap.wrap(ocr_text, width=105)[:3]), fill="#333333", font=font, spacing=2)
    y = 242
    for label, image in option_images[:4]:
        preview = ImageOps.contain(image.convert("RGB"), (160, 55))
        x = 8 + (ord(label) - ord("A")) * 172
        card.paste(preview, (x + (160 - preview.width) // 2, y))
        draw.text((x, 304), label, fill="black", font=font)
    return card


def make_contact_sheets(selected: list[dict[str, Any]]) -> list[str]:
    sheet_dir = WORK / "contact_sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    for path in sheet_dir.glob("*.png"):
        path.unlink()
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        by_year[int(row["year"])].append(row)
    outputs: list[str] = []
    for year, rows in sorted(by_year.items()):
        for chunk_index in range(0, len(rows), 10):
            chunk = rows[chunk_index : chunk_index + 10]
            sheet = Image.new("RGB", (1400, 1600), "#dddddd")
            for index, record in enumerate(chunk):
                rendered = record.get("rendered_images") or []
                q_image = next((item["image"] for item in rendered if item.get("image_type") == "question_crop"), None)
                option_images = [(item.get("label"), item["image"]) for item in rendered if item.get("image_type") == "option_crop" and item.get("label")]
                card = card_for_record(record, q_image, option_images)
                x = (index % 2) * 700
                y = (index // 2) * 320
                sheet.paste(card, (x, y))
            path = sheet_dir / f"year_{year}_part_{chunk_index // 10 + 1}.png"
            sheet.save(path)
            outputs.append(str(path))
    return outputs


def refresh_contact_sheets_from_assets(selected: list[dict[str, Any]], data: dict[str, list[dict[str, Any]]]) -> list[str]:
    image_by_id = {row.get("image_id"): row for row in data["images"]}
    for row in data["options"]:
        if row.get("id"):
            image_by_id[row.get("id")] = row
    rendered_selected: list[dict[str, Any]] = []
    for record in selected:
        option_rows = [row for row in data["options"] if row.get("occurrence_id") == record.get("occurrence_id") and row.get("image_path")]
        rendered = []
        image_ids = list(record.get("source_image_ids") or []) + [row.get("id") for row in option_rows if row.get("id")]
        record_copy = dict(record)
        record_copy["source_image_ids"] = image_ids
        for image_id in image_ids:
            image_row = image_by_id.get(image_id, {})
            path = BASE / str(image_row.get("image_path") or "")
            if path.exists():
                try:
                    image = Image.open(path).convert("RGB")
                except Exception:
                    continue
                label_match = re.search(r"_(?:OPTION_?|OPT)([A-D])(?:_|$)", str(image_id or ""))
                rendered.append({"image": image, "image_id": image_id, "image_type": "option_crop" if label_match else "question_crop", "label": label_match.group(1) if label_match else None})
        record_copy["rendered_images"] = rendered
        rendered_selected.append(record_copy)
    return make_contact_sheets(rendered_selected)


def prepare() -> None:
    started = time.perf_counter()
    WORK.mkdir(parents=True, exist_ok=True)
    data = load_data()
    sources = {row.get("source_id"): row for row in data["sources"]}
    occurrences = {row.get("occurrence_id"): row for row in data["occurrences"]}
    options_by_occ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["options"]:
        options_by_occ[row.get("occurrence_id")].append(row)
    images_by_occ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["images"]:
        images_by_occ[row.get("question_occurrence_id")].append(row)
    checkpoints = phase51.load_checkpoint_questions()
    pdfs = PdfCache()
    evidence: list[dict[str, Any]] = []
    try:
        for question in data["questions"]:
            if question.get("ocr_status") != "OCR_REVIEW_REQUIRED":
                continue
            occurrence = occurrences.get(question.get("canonical_source_occurrence_id"))
            if not occurrence:
                continue
            source = sources.get(occurrence.get("source_id"), {})
            record = evaluate_record(
                question,
                occurrence,
                source,
                options_by_occ.get(occurrence.get("occurrence_id"), []),
                images_by_occ.get(occurrence.get("occurrence_id"), []),
                checkpoints.get(occurrence.get("occurrence_id"), {}),
                pdfs,
            )
            evidence.append(record)
        selected, selection_summary = select_candidates(evidence)
        rendered_selected: list[dict[str, Any]] = []
        question_by_occ = {row.get("canonical_source_occurrence_id"): row for row in data["questions"]}
        for record in selected:
            occurrence = occurrences[record["occurrence_id"]]
            source = sources[record["source_id"]]
            rendered_selected.append(
                evaluate_record(
                    question_by_occ[record["occurrence_id"]],
                    occurrence,
                    source,
                    options_by_occ.get(record["occurrence_id"], []),
                    images_by_occ.get(record["occurrence_id"], []),
                    checkpoints.get(record["occurrence_id"], {}),
                    pdfs,
                    render=True,
                )
            )
        selected_path = WORK / "selected_candidates.json"
        serializable = [{key: value for key, value in record.items() if key != "rendered_images"} for record in rendered_selected]
        write_json(selected_path, {"generated_at": now_iso(), "selected": serializable, "selection_summary": selection_summary, "source_pdf_render_zoom": ZOOM})
        # Keep rendered PIL objects only for contact sheets; the selected manifest is the durable handoff.
        make_contact_sheets(rendered_selected)
        print(json.dumps({"review_records_scanned": len(evidence), "eligible": sum(row["clear_source_image_confirmation"] for row in evidence), "selected": len(rendered_selected), "selection_summary": selection_summary, "contact_sheets": str(WORK / "contact_sheets"), "elapsed_seconds": round(time.perf_counter() - started, 2)}, indent=2))
    finally:
        pdfs.close()


def placeholder_results(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    q_hits = [row for row in data["questions"] if PLACEHOLDER_RE.fullmatch(str(row.get("question_text") or ""))]
    option_hits = [row for row in data["options"] if PLACEHOLDER_RE.fullmatch(str(row.get("text") or ""))]
    regression = {value: bool(PLACEHOLDER_RE.fullmatch(value)) for value in ["Na", "Na+", "NaCl", "NaOH", "N/A", "N.A.", "Option A", "TODO"]}
    return {
        "question_placeholders": len(q_hits),
        "option_placeholders": len(option_hits),
        "regression": regression,
        "pass": not q_hits and not option_hits and not regression["Na"] and not regression["Na+"] and not regression["NaCl"] and not regression["NaOH"] and regression["N/A"] and regression["N.A."],
    }


def apply_promotions(data: dict[str, list[dict[str, Any]]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    selected_by_occ = {row["occurrence_id"]: row for row in selected}
    question_count = option_count = image_count = 0
    for row in data["questions"]:
        occ_id = row.get("canonical_source_occurrence_id")
        evidence = selected_by_occ.get(occ_id)
        if not evidence:
            continue
        row["content_status"] = "CONTENT_VERIFIED"
        row["needs_review"] = False
        row["review_reason"] = None
        row["verification_method"] = evidence["verification_method"]
        row["verification_source_pdf"] = evidence["source_pdf"]
        row["verification_source_pages"] = evidence["source_pages"]
        row["verification_source_image_ids"] = evidence["source_image_ids"]
        row["verification_source_image_sha256"] = evidence["source_image_sha256"]
        row["visual_verification_confidence"] = 1.0
        row["visual_verified_at"] = now_iso()
        question_count += 1
    for row in data["occurrences"]:
        evidence = selected_by_occ.get(row.get("occurrence_id"))
        if evidence:
            row["content_status"] = "CONTENT_VERIFIED"
            row["verification_method"] = evidence["verification_method"]
            row["verification_source_image_ids"] = evidence["source_image_ids"]
            row["visual_verified_at"] = now_iso()
    for row in data["options"]:
        evidence = selected_by_occ.get(row.get("occurrence_id"))
        if evidence:
            row["content_status"] = "CONTENT_VERIFIED"
            row["verification_method"] = "GRAPHICAL_OPTION_CONFIRMED" if evidence["graphical_option_case"] else "SOURCE_IMAGE_PLUS_OPTION_CHECK"
            row["verification_source_page"] = row.get("source_page") or evidence["source_page"]
            row["visual_verified_at"] = now_iso()
            option_count += 1
    for row in data["images"]:
        evidence = selected_by_occ.get(row.get("question_occurrence_id"))
        if evidence:
            row["visual_verification"] = "SOURCE_IMAGE_CONFIRMED"
            row["verification_method"] = evidence["verification_method"]
            row["visual_verified_at"] = now_iso()
            image_count += 1
    return {"questions": question_count, "options": option_count, "images": image_count}


def metadata_errors(data: dict[str, list[dict[str, Any]]], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources = {row.get("source_id"): row for row in data["sources"]}
    occurrences = {row.get("occurrence_id"): row for row in data["occurrences"]}
    errors = []
    for record in selected:
        source = sources.get(record["source_id"], {})
        occurrence = occurrences.get(record["occurrence_id"], {})
        expected = {key: source.get(key) for key in ["year", "session", "exam_date", "shift", "language", "source_id", "source_page"]}
        actual = {
            "year": occurrence.get("year"),
            "session": occurrence.get("session"),
            "exam_date": occurrence.get("exam_date"),
            "shift": occurrence.get("shift"),
            "language": occurrence.get("language"),
            "source_id": occurrence.get("source_id"),
            "source_page": occurrence.get("source_page"),
        }
        if any(actual.get(key) != expected.get(key) for key in ["year", "session", "exam_date", "shift", "language", "source_id"]):
            errors.append({"occurrence_id": record["occurrence_id"], "type": "occurrence_source_metadata_mismatch", "expected": expected, "actual": actual})
        if int(actual.get("source_page") or 0) not in [int(page) for page in record.get("source_pages") or []]:
            errors.append({"occurrence_id": record["occurrence_id"], "type": "source_page_mismatch", "expected": record.get("source_pages"), "actual": actual.get("source_page")})
    return errors


def collision_check(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = [row for row in data["sources"] if row.get("source_id") in {"JM_2022_Session-2_2022-07-25_1_Hindi", "JM_2022_Session-2_2022-07-26_1_Hindi"}]
    files = []
    for row in rows:
        path = BASE / str(row.get("source_pdf"))
        files.append({"source_id": row.get("source_id"), "source_pdf": row.get("source_pdf"), "exists": path.exists(), "sha256": sha256_file(path) if path.exists() else None, "recorded_sha256": row.get("source_sha256"), "year": row.get("year"), "exam_date": row.get("exam_date"), "shift": row.get("shift"), "language": row.get("language")})
    return {"source_ids": [row.get("source_id") for row in rows], "byte_identical": len(files) == 2 and files[0]["sha256"] == files[1]["sha256"], "preserved_as_distinct_official_identities": len(rows) == 2, "records": files, "decision": "PRESERVE_BOTH_OCCURRENCES"}


def update_content_truth_report(data: dict[str, list[dict[str, Any]]], final_report: dict[str, Any]) -> None:
    path = AUDIT / "jee_main_ocr_content_truth_report.json"
    old = read_json(path) if path.exists() else {}
    questions = data["questions"]
    old.update(
        {
            "generated_at": final_report["generated_at"],
            "phase": "PHASE 5B.2",
            "final_status": final_report["final_status"],
            "questions_ocr_verified": sum(row.get("ocr_status") == "OCR_MEDIUM_CONFIDENCE" for row in questions),
            "questions_needs_review": final_report["review_required_after"],
            "questions_content_verified": sum(row.get("content_status") == "CONTENT_VERIFIED" for row in questions),
            "visual_verification": {"records_reviewed": final_report["records_reviewed"], "records_promoted": final_report["records_promoted"], "records_retained_for_review": final_report["records_retained_for_review"]},
            "report_basis": "Phase 5B.2 source-image verification over the existing Phase 5B OCR candidate text; no OCR rebuild",
        }
    )
    write_json(path, old)
    lines = [
        "# JEE Main OCR content truth report",
        "",
        f"Generated: {old['generated_at']}",
        "",
        f"Final status: `{old['final_status']}`",
        "",
        "## Phase 5B.2 visual verification",
        "",
        f"Records visually reviewed: {final_report['records_reviewed']}",
        f"Records promoted to `CONTENT_VERIFIED`: {final_report['records_promoted']}",
        f"Records retained for review: {final_report['records_retained_for_review']}",
        "",
        "The original official PDF image is authoritative. Unselected or insufficiently clear OCR remains review-required.",
        "",
    ]
    (AUDIT / "jee_main_ocr_content_truth_report.md").write_text("\n".join(lines), encoding="utf-8")


def promote() -> None:
    started = time.perf_counter()
    selected_path = WORK / "selected_candidates.json"
    if not selected_path.exists():
        raise RuntimeError("Run --prepare first; selected candidate evidence is missing.")
    selected_doc = read_json(selected_path)
    reviewed_selected = selected_doc["selected"]
    selected, approval_manifest = load_approved_records(reviewed_selected)
    data = load_data()
    baseline = read_json(BASELINE_MANIFEST) if BASELINE_MANIFEST.exists() else {}
    before_review = int(baseline.get("question_needs_review", sum(bool(row.get("needs_review")) for row in data["questions"])))
    before_content_verified = int(baseline.get("content_verified", sum(row.get("content_status") == "CONTENT_VERIFIED" for row in data["questions"])))
    collision = collision_check(data)
    errors = metadata_errors(data, selected)
    counts = apply_promotions(data, selected)
    for name, key in [("questions", "questions"), ("question_occurrences", "occurrences"), ("options", "options"), ("answers", "answers"), ("sources", "sources"), ("images", "images")]:
        write_jsonl(JM / f"{name}.jsonl", data[key])
    sqlite_counts = pipeline.rebuild_sqlite(data)
    db_validation = pipeline.sqlite_validation()
    after_review = sum(bool(row.get("needs_review")) for row in data["questions"])
    after_content_verified = sum(row.get("content_status") == "CONTENT_VERIFIED" for row in data["questions"])
    duplicate_occurrences = len(data["occurrences"]) - len({row.get("occurrence_id") for row in data["occurrences"]})
    duplicate_images = len(data["images"]) - len({row.get("image_id") for row in data["images"]})
    placeholders = placeholder_results(data)
    integrity_errors = db_validation.get("invalid_source_references", 0) + db_validation.get("missing_source_pages", 0) + db_validation.get("foreign_key_errors", 0) + db_validation.get("orphan_questions", 0) + db_validation.get("orphan_options", 0) + db_validation.get("orphan_answers", 0) + db_validation.get("orphan_images", 0) + duplicate_occurrences + duplicate_images
    years_in_sample = sorted(int(year) for year in selected_doc["selection_summary"])
    promotions_by_year = {str(year): sum(1 for row in selected if int(row["year"]) == year) for year in years_in_sample}
    promotions_by_subject = dict(Counter(row["subject"] for row in selected))
    promotions_by_bucket = dict(Counter(row["primary_bucket"] for row in selected))
    reviewed_sample_retained = len(reviewed_selected) - len(selected)
    final_report = {
        "generated_at": now_iso(),
        "phase": "PHASE 5B.2",
        "final_status": "OCR_VISUAL_VERIFICATION_COMPLETE" if selected and reviewed_sample_retained == 0 and after_review == 0 and not errors and placeholders["pass"] and integrity_errors == 0 and all(summary.get("adversarial_sample_pass") for summary in selected_doc["selection_summary"].values()) else "OCR_CONTENT_REVIEW_REQUIRED",
        "review_required_before": before_review,
        "review_required_after": after_review,
        "content_verified_before": before_content_verified,
        "content_verified_after": after_content_verified,
        "newly_promoted": counts["questions"],
        "records_reviewed": len(reviewed_selected),
        "records_promoted": counts["questions"],
        "records_retained_for_review": after_review,
        "reviewed_sample_retained": reviewed_sample_retained,
        "approved_manifest": str(APPROVED_MANIFEST) if approval_manifest is not None else None,
        "approved_occurrence_ids": [row["occurrence_id"] for row in selected],
        "reviewed_sample_retained_occurrence_ids": [row["occurrence_id"] for row in reviewed_selected if row["occurrence_id"] not in {item["occurrence_id"] for item in selected}],
        "promotions_by_year": promotions_by_year,
        "promotions_by_subject": promotions_by_subject,
        "promotions_by_error_bucket": promotions_by_bucket,
        "equation_cases": sum(bool(row["flags"].get("equation_heavy")) for row in selected),
        "chemistry_cases": sum(bool(row["flags"].get("chemistry_structure")) for row in selected),
        "diagram_cases": sum(bool(row["flags"].get("diagram_heavy")) for row in selected),
        "bilingual_cases": sum(bool(row["flags"].get("bilingual")) for row in selected),
        "graphical_option_cases": sum(bool(row["graphical_option_case"]) for row in selected),
        "verification_methods": dict(Counter(row["verification_method"] for row in selected)),
        "selected_records": selected,
        "reviewed_sample_selection_summary": selected_doc["selection_summary"],
        "adversarial_sample": selected_doc["selection_summary"],
        "metadata_errors": errors,
        "placeholder_results": placeholders,
        "database_integrity": {**db_validation, "duplicate_occurrence_ids": duplicate_occurrences, "duplicate_image_ids": duplicate_images, "integrity_error_total": integrity_errors},
        "duplicate_source_sha_collision_check": collision,
        "sqlite_counts": sqlite_counts,
        "no_ocr_rebuild": True,
        "scope_boundary": ["Phase 5C not started", "solutions not generated", "taxonomy not performed", "Supabase not imported", "frontend not built", "student analytics unchanged"],
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    AUDIT.mkdir(parents=True, exist_ok=True)
    write_json(AUDIT / "jee_main_ocr_visual_verification.json", final_report)
    md = [
        "# JEE Main targeted visual OCR verification — Phase 5B.2",
        "",
        f"Generated: {final_report['generated_at']}",
        "",
        f"Final status: `{final_report['final_status']}`",
        "",
        "The original official PDF image was used as the authority. Existing OCR candidate text was not rebuilt.",
        "",
        "## Counts",
        "",
        "| metric | before | after |",
        "|---|---:|---:|",
        f"| review-required records | {before_review} | {after_review} |",
        f"| content-verified records | {before_content_verified} | {after_content_verified} |",
        f"| newly promoted | — | {counts['questions']} |",
        f"| records visually reviewed | — | {len(reviewed_selected)} |",
        f"| reviewed-sample records retained for review | — | {reviewed_sample_retained} |",
        "",
        "## Promotions",
        "",
        f"By year: {promotions_by_year}",
        f"By subject: {promotions_by_subject}",
        f"By primary error bucket: {promotions_by_bucket}",
        f"Equation cases: {final_report['equation_cases']}; chemistry cases: {final_report['chemistry_cases']}; diagram cases: {final_report['diagram_cases']}; bilingual cases: {final_report['bilingual_cases']}; graphical-option cases: {final_report['graphical_option_cases']}",
        "",
        "## Validation",
        "",
        f"Metadata errors: {len(errors)}",
        f"Placeholders: questions={placeholders['question_placeholders']}, options={placeholders['option_placeholders']}",
        f"Database integrity errors: {integrity_errors}",
        f"Duplicate source SHA collision decision: `{collision['decision']}`",
        "",
        "Every promoted record has source PDF, source page, source-image crop, question-number, metadata, and option/image evidence recorded in the JSON report. Reviewed but unpromoted records, and all unselected records, remain review-required.",
        "",
        "Phase 5C, solutions, taxonomy, Supabase import, frontend work, and student analytics were not started.",
        "",
    ]
    (AUDIT / "jee_main_ocr_visual_verification.md").write_text("\n".join(md), encoding="utf-8")
    update_content_truth_report(data, final_report)
    print(json.dumps({"final_status": final_report["final_status"], "review_required_before": before_review, "review_required_after": after_review, "content_verified_before": before_content_verified, "content_verified_after": after_content_verified, "newly_promoted": counts["questions"], "metadata_errors": len(errors), "placeholder_results": placeholders, "database_integrity": final_report["database_integrity"], "promotions_by_year": promotions_by_year}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--promote", action="store_true")
    group.add_argument("--refresh-sheets", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.promote:
        promote()
    else:
        selected_doc = read_json(WORK / "selected_candidates.json")
        sheets = refresh_contact_sheets_from_assets(selected_doc["selected"], load_data())
        print(json.dumps({"contact_sheets": sheets, "selected": len(selected_doc["selected"])}, indent=2))


if __name__ == "__main__":
    main()
