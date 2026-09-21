"""Phase 5B.1 source/OCR reconciliation for the JEE Main database.

This pass is deliberately conservative.  It corrects only four source metadata
records supported by the official PDF's first-page paper name and the existing
official coverage evidence.  It does not promote OCR text to verified content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ocr_reconstruct_jee_main as pipeline


BASE = Path(__file__).resolve().parent
FINAL = BASE / "JEE_QUESTION_DATABASE_FINAL"
JM = FINAL / "JEE_MAIN"
AUDIT = BASE / "audit"
MANIFEST = BASE / "JEE_Main_PYQ_Archive" / "jee_main_official_paper_manifest.json"

PLACEHOLDER_RE = re.compile(
    r"^(?:question\s*(?:text|x|\d+)?|placeholder|sample question|generated question|"
    r"option\s*[abcd]|tbd|todo|n/a|n\.a\.)$",
    re.I,
)
SUSPICIOUS_RE = pipeline.SUSPICIOUS_RE
EQUATION_RE = re.compile(r"(?:[=^_√∫∑≤≥≠π]|\b(?:sin|cos|tan|log|ln|exp)\b|\d\s*[A-Za-z]\b)", re.I)
CHEMISTRY_RE = re.compile(r"\b(?:Na|Na\+|NaCl|NaOH|HCl|H2O|CO2|NH3|CH4)\b|[A-Z][a-z]?\d", re.I)

# Evidence is recorded in the generated anomaly report.  The original PDF
# path and SHA are intentionally unchanged; only the semantic source metadata
# and dependent IDs are corrected.
SOURCE_CORRECTIONS: dict[str, dict[str, Any]] = {
    "JM_2021_Session-3_2021-07-27_2": {
        "new_source_id": "JM_2021_Session-3_2021-07-20_2",
        "year": 2021,
        "exam_date": "2021-07-20",
        "evidence": "PDF first-page paper name: B Tech 20072021 Shift 2",
    },
    "JM_2021_Session-3_2021-07-27_2_Hindi": {
        "new_source_id": "JM_2021_Session-3_2021-07-20_2_Hindi",
        "year": 2021,
        "exam_date": "2021-07-20",
        "evidence": "PDF first-page paper name: B Tech 20072021 Shift 2",
    },
    "JM_2024_Session-1_2025-02-01_2_English_Hindi": {
        "new_source_id": "JM_2024_Session-1_2024-02-01_2_English_Hindi",
        "year": 2024,
        "exam_date": "2024-02-01",
        "evidence": "PDF first-page paper name: B Tech 1st Feb 2024 Shift 2",
    },
    "JM_2025_Session-1_2024-01-29_1_English_Hindi": {
        "new_source_id": "JM_2024_Session-1_2024-01-29_1_English_Hindi",
        "year": 2024,
        "exam_date": "2024-01-29",
        "evidence": "PDF first-page paper name: B Tech 29th Jan 2024 Shift 1; official coverage inventory places 2024-01-29 in the 2024 set",
    },
}
CORRECTIONS_BY_EFFECTIVE_ID = {
    correction["new_source_id"]: (old_source_id, correction)
    for old_source_id, correction in SOURCE_CORRECTIONS.items()
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        tmp.replace(path)
    except PermissionError:
        # Windows can transiently deny replacement of a generated JSONL file
        # held by an indexer.  The destination is always an exact workspace
        # output and has already been fully rewritten in `tmp`.
        path.unlink(missing_ok=True)
        tmp.replace(path)


def norm_path(value: str | None) -> str:
    return str(value or "").replace("\\", "/").lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remap_prefix(value: str | None, old: str, new: str) -> str | None:
    if value and value.startswith(old):
        return new + value[len(old):]
    return value


def load_data() -> dict[str, list[dict[str, Any]]]:
    return {
        "sources": read_jsonl(JM / "sources.jsonl"),
        "questions": read_jsonl(JM / "questions.jsonl"),
        "occurrences": read_jsonl(JM / "question_occurrences.jsonl"),
        "options": read_jsonl(JM / "options.jsonl"),
        "answers": read_jsonl(JM / "answers.jsonl"),
        "images": read_jsonl(JM / "images.jsonl"),
    }


def canonical_source_rows(data: dict[str, list[dict[str, Any]]], manifest: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], dict[str, dict[str, Any]], dict[str, Any]]:
    current_by_path = {norm_path(row.get("source_pdf") or row.get("local_path")): row for row in data["sources"]}
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(manifest, 1):
        groups[norm_path(row.get("local_path"))].append((index, row))

    source_rows: list[dict[str, Any]] = []
    manifest_detail: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}
    source_meta: dict[str, dict[str, Any]] = {}
    correction_rows: list[dict[str, Any]] = []
    source_hash_collisions: dict[str, list[str]] = defaultdict(list)

    for path_key, members in sorted(groups.items(), key=lambda item: item[1][0][0]):
        manifest_index, manifest_row = members[0]
        current = current_by_path.get(path_key)
        if current is None:
            raise RuntimeError(f"manifest source missing from OCR sources.jsonl: {manifest_row.get('local_path')}")
        old_id = current["source_id"]
        correction = SOURCE_CORRECTIONS.get(old_id)
        correction_prior_id = old_id
        if correction is None and old_id in CORRECTIONS_BY_EFFECTIVE_ID:
            correction_prior_id, correction = CORRECTIONS_BY_EFFECTIVE_ID[old_id]
        new_id = correction["new_source_id"] if correction else old_id
        old_to_new[old_id] = new_id

        effective = dict(current)
        effective.update(
            {
                "source_id": new_id,
                "year": int(manifest_row["year"]),
                "session": manifest_row.get("session"),
                "exam_date": manifest_row.get("exam_date"),
                "shift": int(manifest_row["shift"]),
                "language": manifest_row.get("language"),
                "paper_type": manifest_row.get("paper_type") or "B.E./B.Tech.",
                "source_pdf": manifest_row.get("local_path"),
                "local_path": manifest_row.get("local_path"),
                "source_url": manifest_row.get("qp_url") or manifest_row.get("source_page"),
                "manifest_row_count": len(members),
            }
        )
        if correction:
            effective["year"] = correction["year"]
            effective["exam_date"] = correction["exam_date"]
            correction_rows.append(
                {
                    "old_source_id": correction_prior_id,
                    "new_source_id": new_id,
                    "manifest_metadata": {k: manifest_row.get(k) for k in ["year", "session", "exam_date", "shift", "language", "paper_type", "qp_url", "local_path"]},
                    "effective_metadata": {k: effective.get(k) for k in ["year", "session", "exam_date", "shift", "language", "paper_type", "source_url", "local_path", "source_sha256"]},
                    "evidence": correction["evidence"],
                    "action": "FIXED_IN_DATABASE",
                    "already_applied_before_this_run": correction_prior_id != old_id,
                }
            )
        source_rows.append(effective)
        source_meta[new_id] = effective
        source_hash_collisions[str(effective.get("source_sha256"))].append(new_id)

        for member_index, member in members:
            is_duplicate = member_index != manifest_index
            manifest_detail.append(
                {
                    "manifest_row_index": member_index,
                    "local_path": member.get("local_path"),
                    "source_id": new_id,
                    "prior_source_id": old_id,
                    "source_status": effective.get("source_status"),
                    "consolidation_reason": "duplicate_manifest_row" if is_duplicate else "canonical_source_row",
                    "consolidated_into": new_id,
                    "explanation": (
                        f"Manifest row duplicates row {manifest_index} for the same local PDF; retained in inventory and processed once."
                        if is_duplicate
                        else f"Canonical local PDF row; {len(members) - 1} duplicate manifest row(s) consolidated into this source."
                    ),
                }
            )

    for sha, ids in source_hash_collisions.items():
        if sha and len(ids) > 1:
            for source_id in ids:
                source_meta[source_id]["exact_sha256_collision_group"] = ids

    summary = {
        "manifest_rows_selected": len(manifest),
        "consolidated_sources": len(source_rows),
        "duplicate_manifest_rows_collapsed": len(manifest) - len(source_rows),
        "successful_sources": sum(row.get("source_status") == "VALID_SOURCE_PDF" for row in source_rows),
        "corrupt_sources": sum(row.get("source_status") == "SOURCE_CORRUPT" for row in source_rows),
        "partial_sources": sum(row.get("source_status") == "SOURCE_PARTIAL" for row in source_rows),
        "excluded_or_unprocessed_canonical_sources": 0,
        "exact_sha256_collision_groups": [ids for sha, ids in source_hash_collisions.items() if sha and len(ids) > 1],
    }
    return source_rows, manifest_detail, old_to_new, source_meta, {"summary": summary, "corrections": correction_rows, "current_by_path": current_by_path}


def reconcile_metadata(source_rows: list[dict[str, Any]], manifest_detail: list[dict[str, Any]], current_by_path: dict[str, dict[str, Any]]) -> dict[str, Any]:
    filename_conflicts: list[dict[str, Any]] = []
    for row in source_rows:
        path = str(row.get("source_pdf") or "")
        basename = Path(path).name
        year_match = re.search(r"JEE_Main_(20\d{2})_", basename)
        date_match = re.search(r"_(20\d{2}-\d{2}-\d{2})_Shift", basename)
        checks = []
        if year_match and str(row.get("year")) != year_match.group(1):
            checks.append({"type": "filename_year_mismatch", "filename_year": int(year_match.group(1)), "database_year": row.get("year")})
        if date_match and row.get("exam_date") != date_match.group(1):
            checks.append({"type": "filename_date_mismatch", "filename_date": date_match.group(1), "database_date": row.get("exam_date")})
        directory_match = re.search(r"JEE_Main_PYQ_Archive/(20\d{2})/", path.replace("\\", "/"))
        if directory_match and str(row.get("year")) != directory_match.group(1):
            checks.append({"type": "archive_directory_year_mismatch", "directory_year": int(directory_match.group(1)), "database_year": row.get("year")})
        if checks:
            filename_conflicts.append({"source_id": row.get("source_id"), "source_pdf": path, "checks": checks, "disposition": "PRESERVED_ORIGINAL_PATH_AND_EXPLICITLY_DOCUMENTED"})

    source_checks = []
    for row in source_rows:
        path = BASE / str(row.get("source_pdf") or "")
        exists = path.exists()
        actual_sha = sha256_file(path) if exists else None
        source_checks.append(
            {
                "source_id": row.get("source_id"),
                "source_pdf": row.get("source_pdf"),
                "required_fields_present": all(row.get(k) not in (None, "") for k in ["year", "session", "exam_date", "shift", "language", "paper_type", "source_url", "source_pdf", "source_sha256"]),
                "local_path_exists": exists,
                "sha256_matches_local_pdf": bool(exists and actual_sha == row.get("source_sha256")),
                "computed_sha256": actual_sha,
                "source_status": row.get("source_status"),
            }
        )
    return {
        "automated_checks": {
            "source_count": len(source_rows),
            "required_field_failures": sum(not r["required_fields_present"] for r in source_checks),
            "missing_local_pdfs": sum(not r["local_path_exists"] for r in source_checks),
            "sha256_mismatches": sum(not r["sha256_matches_local_pdf"] for r in source_checks),
            "filename_or_archive_conflict_count": len(filename_conflicts),
        },
        "filename_or_archive_conflicts_preserved": filename_conflicts,
        "source_checks": source_checks,
        "unresolved_semantic_anomalies": [],
    }


def remap_records(data: dict[str, list[dict[str, Any]]], old_to_new: dict[str, str], source_meta: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    occurrence_map: dict[str, str] = {}
    for row in data["occurrences"]:
        old_source = row.get("source_id")
        new_source = old_to_new.get(old_source, old_source)
        new_occurrence = remap_prefix(row.get("occurrence_id"), old_source or "", new_source or "") or row.get("occurrence_id")
        occurrence_map[row.get("occurrence_id")] = new_occurrence
        row["occurrence_id"] = new_occurrence
        row["source_id"] = new_source
        meta = source_meta[new_source]
        for key in ["year", "session", "exam_date", "shift", "language"]:
            row[key] = meta.get(key)
        row["source_pdf"] = meta.get("source_pdf")

    for row in data["sources"]:
        new_source = old_to_new.get(row.get("source_id"), row.get("source_id"))
        row.update(source_meta[new_source])

    for row in data["questions"]:
        row["canonical_source_occurrence_id"] = occurrence_map.get(row.get("canonical_source_occurrence_id"), row.get("canonical_source_occurrence_id"))

    for row in data["options"]:
        old_occ = row.get("occurrence_id")
        row["occurrence_id"] = occurrence_map.get(old_occ, old_occ)
        row["id"] = remap_prefix(row.get("id"), old_occ or "", row.get("occurrence_id") or "") or row.get("id")

    for row in data["answers"]:
        old_occ = row.get("occurrence_id")
        row["occurrence_id"] = occurrence_map.get(old_occ, old_occ)
        row["answer_id"] = remap_prefix(row.get("answer_id"), old_occ or "", row.get("occurrence_id") or "") or row.get("answer_id")
        old_source = row.get("source_id")
        new_source = old_to_new.get(old_source, old_source)
        row["source_id"] = new_source
        meta = source_meta[new_source]
        for key in ["year", "session", "exam_date", "shift"]:
            row[key] = meta.get(key)

    for row in data["images"]:
        old_occ = row.get("question_occurrence_id")
        row["question_occurrence_id"] = occurrence_map.get(old_occ, old_occ)
        row["image_id"] = remap_prefix(row.get("image_id"), old_occ or "", row.get("question_occurrence_id") or "") or row.get("image_id")

    return data


def load_checkpoint_questions() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in (FINAL / "ocr_checkpoints").glob("v5_*.json"):
        try:
            checkpoint = read_json(path)
        except Exception:
            continue
        for question in checkpoint.get("questions", []):
            out[question.get("occurrence_id")] = question
    return out


def review_buckets(data: dict[str, list[dict[str, Any]]], source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    occurrences = {row.get("occurrence_id"): row for row in data["occurrences"]}
    options_by_occ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["options"]:
        options_by_occ[row.get("occurrence_id")].append(row)
    images_by_occ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["images"]:
        images_by_occ[row.get("question_occurrence_id")].append(row)
    checkpoints = load_checkpoint_questions()
    sources = {row.get("source_id"): row for row in source_rows}
    review_rows = [row for row in data["questions"] if row.get("ocr_status") == "OCR_REVIEW_REQUIRED"]
    names = ["low_ocr_confidence", "engine_disagreement", "equation_heavy", "chemistry_structure", "diagram_heavy", "malformed_options", "suspicious_characters", "incomplete_text", "bilingual", "metadata_source_uncertainty", "multi_page", "genuinely_unresolved"]
    flags = Counter()
    primary = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    priority = ["metadata_source_uncertainty", "engine_disagreement", "malformed_options", "incomplete_text", "suspicious_characters", "equation_heavy", "chemistry_structure", "diagram_heavy", "bilingual", "multi_page", "low_ocr_confidence", "genuinely_unresolved"]
    for q in review_rows:
        occ_id = q.get("canonical_source_occurrence_id")
        occ = occurrences.get(occ_id, {})
        cp = checkpoints.get(occ_id, {})
        source = sources.get(occ.get("source_id"), {})
        opts = options_by_occ.get(occ_id, [])
        assets = images_by_occ.get(occ_id, [])
        text = str(q.get("question_text") or "")
        labels = {str(o.get("label")) for o in opts}
        row_flags = {
            "low_ocr_confidence": float(q.get("ocr_confidence") or 0) < 0.5,
            "engine_disagreement": bool(cp.get("pass2_disagreement")),
            "equation_heavy": bool(EQUATION_RE.search(text)),
            "chemistry_structure": str(q.get("subject")) == "Chemistry" or bool(CHEMISTRY_RE.search(text)),
            "diagram_heavy": any(a.get("image_type") == "diagram_crop" for a in assets),
            "malformed_options": str(q.get("question_type") or "").upper() == "MCQ" and not {"A", "B", "C", "D"}.issubset(labels),
            "suspicious_characters": bool(SUSPICIOUS_RE.search(text)),
            "incomplete_text": len(text.strip()) < 40 or not text.strip(),
            "bilingual": source.get("language") in {"English_Hindi", "Hindi"},
            "metadata_source_uncertainty": source.get("source_status") in {"SOURCE_CORRUPT", "SOURCE_PARTIAL"} or source.get("source_id") in SOURCE_CORRECTIONS,
            "multi_page": len(occ.get("source_pages") or []) > 1,
        }
        for name, active in row_flags.items():
            if active:
                flags[name] += 1
        selected = next((name for name in priority if row_flags[name]), "genuinely_unresolved")
        primary[selected] += 1
        if len(examples[selected]) < 5:
            examples[selected].append(occ_id)
    return {
        "review_required_records": len(review_rows),
        "bucket_counts_overlapping": {name: flags[name] for name in names},
        "primary_bucket_counts_exclusive": {name: primary[name] for name in names},
        "primary_bucket_examples": dict(examples),
        "checkpoint_pass2_evidence_records": sum(bool(checkpoints.get(q.get("canonical_source_occurrence_id"), {}).get("ocr_pass2_texts")) for q in review_rows),
        "additional_targeted_reprocessing": 0,
        "additional_reprocessing_reason": "Phase 5B v5 already retained pass-2 OCR evidence; no independent OCR engine or deterministic source-image consensus was available for safe promotion, so uncertain records remain review-required.",
    }


def validate_placeholders(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    q_hits = []
    option_hits = []
    for row in data["questions"]:
        value = str(row.get("question_text") or "")
        if PLACEHOLDER_RE.fullmatch(value):
            q_hits.append({"question_id": row.get("question_id"), "value": value})
    for row in data["options"]:
        value = str(row.get("text") or "")
        if PLACEHOLDER_RE.fullmatch(value):
            option_hits.append({"id": row.get("id"), "value": value})
    regression = {value: bool(PLACEHOLDER_RE.fullmatch(value)) for value in ["Na", "Na+", "NaCl", "NaOH", "N/A", "N.A.", "Option A", "TODO"]}
    return {"question_placeholders": len(q_hits), "option_placeholders": len(option_hits), "hits": q_hits + option_hits, "regression": regression, "pass": not q_hits and not option_hits and regression["Na"] is False and regression["Na+"] is False and regression["NaCl"] is False and regression["NaOH"] is False and regression["N/A"] is True and regression["N.A."] is True}


def validate_options(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    occurrence_map = {row.get("occurrence_id"): row for row in data["occurrences"]}
    options_by_occ: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["options"]:
        options_by_occ[row.get("occurrence_id")].append(row)
    checked = complete = missing = duplicate = graphical = 0
    for occurrence_id, occurrence in occurrence_map.items():
        if str(occurrence.get("question_type") or "").upper() != "MCQ":
            continue
        checked += 1
        rows = options_by_occ.get(occurrence_id, [])
        labels = [str(row.get("label")) for row in rows]
        if len(labels) != len(set(labels)):
            duplicate += 1
        if {"A", "B", "C", "D"}.issubset(set(labels)):
            complete += 1
        else:
            missing += 1
            if any(row.get("image_path") for row in rows):
                graphical += 1
    return {
        "mcq_occurrences_checked": checked,
        "abcd_complete": complete,
        "missing_abcd": missing,
        "missing_with_graphical_evidence": graphical,
        "visual_option_occurrences_retained": graphical,
        "duplicate_option_label_occurrences": duplicate,
        "pass": (missing == 0 or graphical == missing) and duplicate == 0,
    }


def bilingual_reconciliation(source_rows: list[dict[str, Any]], occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row.get("language") for row in source_rows)
    occurrence_counts = Counter(row.get("source_id") for row in occurrences)
    result = {
        "definition": "English_Hindi is counted as an explicitly bilingual PDF; Hindi is a Hindi-only variant and is reported separately.",
        "source_language_counts": dict(counts),
        "actual_bilingual_source_pdfs": counts.get("English_Hindi", 0),
        "actual_bilingual_recovered": sum(1 for row in source_rows if row.get("language") == "English_Hindi" and occurrence_counts[row.get("source_id")]),
        "actual_bilingual_unresolved": sum(1 for row in source_rows if row.get("language") == "English_Hindi" and not occurrence_counts[row.get("source_id")]),
        "hindi_variant_source_pdfs": counts.get("Hindi", 0),
        "hindi_variant_recovered": sum(1 for row in source_rows if row.get("language") == "Hindi" and occurrence_counts[row.get("source_id")]),
        "hindi_variant_unresolved": sum(1 for row in source_rows if row.get("language") == "Hindi" and not occurrence_counts[row.get("source_id")]),
        "previous_phase5a_unknown_format_records": 13,
        "previous_unknown_explanation": "The previous Phase 5A count of 13 was UNKNOWN format classification, not a count of bilingual-language PDFs; it is not comparable to the Phase 5B language label count.",
    }
    return result


def full_paper_validation(source_rows: list[dict[str, Any]], occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in occurrences:
        by_source[row.get("source_id")].append(row)
    representatives = []
    for year in sorted({row.get("year") for row in source_rows if row.get("year") is not None}):
        candidates = [(source_id, rows) for source_id, rows in by_source.items() if rows and next((s for s in source_rows if s.get("source_id") == source_id and s.get("year") == year), None)]
        if not candidates:
            continue
        source_id, rows = max(candidates, key=lambda item: len(item[1]))
        source = next(s for s in source_rows if s.get("source_id") == source_id)
        rows = sorted(rows, key=lambda row: (int(row.get("question_number") or 0), row.get("occurrence_id") or ""))
        numbers = [int(row.get("question_number")) for row in rows if str(row.get("question_number") or "").isdigit()]
        expected = list(range(min(numbers), max(numbers) + 1)) if numbers else []
        subjects = [row.get("subject") for row in rows if row.get("subject")]
        representatives.append(
            {
                "year": year,
                "source_id": source_id,
                "question_count": len(rows),
                "question_sequence_pass": numbers == expected and len(numbers) == len(set(numbers)),
                "subject_order_present": bool(subjects),
                "subject_runs": list(dict.fromkeys(subjects)),
                "all_source_pages_present": all(int(row.get("source_page") or 0) >= 1 for row in rows),
                "metadata_present": all(source.get(k) not in (None, "") for k in ["year", "session", "exam_date", "shift", "language", "paper_type", "source_url", "source_pdf", "source_sha256"]),
                "source_status": source.get("source_status"),
            }
        )
    return {"representatives": representatives, "pass": len(representatives) == 7 and all(r["question_sequence_pass"] and r["all_source_pages_present"] and r["metadata_present"] for r in representatives)}


def write_inventory_report(manifest_detail: list[dict[str, Any]]) -> None:
    write_jsonl(AUDIT / "jee_main_source_inventory.jsonl", manifest_detail)
    counts = Counter(row.get("source_status") for row in manifest_detail if row.get("consolidation_reason") == "canonical_source_row")
    lines = ["# JEE Main official Paper-I source inventory", "", f"Generated: {now_iso()}", "", f"Manifest rows: {len(manifest_detail)}", f"Canonical local PDFs: {sum(row.get('consolidation_reason') == 'canonical_source_row' for row in manifest_detail)}", "", "| source_status | canonical count |", "|---|---:|"]
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {value} |")
    (AUDIT / "jee_main_source_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_full_paper_report(report: dict[str, Any]) -> None:
    lines = [
        "# JEE Main full-paper OCR reconstruction report — Phase 5B.1",
        "",
        f"Generated: {now_iso()}",
        "",
        "One representative full paper per year was checked for question sequence, source-page presence, subject runs, and complete source metadata.",
        "",
        "| year | source | effective date | shift | questions | sequence | pages | metadata | subjects | status |",
        "|---:|---|---|---:|---:|---|---|---|---|---|",
    ]
    for row in report["representatives"]:
        subjects = ", ".join(row["subject_runs"]) or "—"
        passed = all(
            [
                row["question_sequence_pass"],
                row["all_source_pages_present"],
                row["metadata_present"],
                row["subject_order_present"],
            ]
        )
        lines.append(
            f"| {row['year']} | `{row['source_id']}` | {row.get('exam_date', '—')} | {row.get('shift', '—')} | "
            f"{row['question_count']} | {'PASS' if row['question_sequence_pass'] else 'FAIL'} | "
            f"{'PASS' if row['all_source_pages_present'] else 'FAIL'} | {'PASS' if row['metadata_present'] else 'FAIL'} | "
            f"{subjects} | {'PASS' if passed else 'FAIL'} |"
        )
    lines.extend(["", f"Overall full-paper validation: **{'PASS' if report['pass'] else 'FAIL'}**", ""])
    (AUDIT / "jee_main_full_ocr_reconstruction_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")
    started = time.perf_counter()
    AUDIT.mkdir(parents=True, exist_ok=True)
    manifest = [row for row in read_json(MANIFEST) if row.get("download_status") == "AVAILABLE_AND_DOWNLOADED"]
    data = load_data()
    before_review = sum(row.get("ocr_status") == "OCR_REVIEW_REQUIRED" for row in data["questions"])
    before_ocr_verified = sum(row.get("ocr_status") == "OCR_MEDIUM_CONFIDENCE" for row in data["questions"])
    before_content_verified = sum(row.get("content_status") == "CONTENT_VERIFIED" for row in data["questions"])
    source_rows, manifest_detail, old_to_new, source_meta, source_context = canonical_source_rows(data, manifest)
    before_occurrences = len(data["occurrences"])
    metadata = reconcile_metadata(source_rows, manifest_detail, source_context["current_by_path"])
    buckets = review_buckets(data, source_rows)
    placeholders = validate_placeholders(data)
    options = validate_options(data)

    data["sources"] = source_rows
    data = remap_records(data, old_to_new, source_meta)
    bilingual = bilingual_reconciliation(source_rows, data["occurrences"])
    write_jsonl(JM / "questions.jsonl", data["questions"])
    write_jsonl(JM / "question_occurrences.jsonl", data["occurrences"])
    write_jsonl(JM / "options.jsonl", data["options"])
    write_jsonl(JM / "answers.jsonl", data["answers"])
    write_jsonl(JM / "sources.jsonl", data["sources"])
    write_jsonl(JM / "images.jsonl", data["images"])
    write_inventory_report(manifest_detail)

    sqlite_counts = pipeline.rebuild_sqlite(data)
    db_validation = pipeline.sqlite_validation()
    data["processed"] = []
    full_paper = full_paper_validation(source_rows, data["occurrences"])
    write_full_paper_report(full_paper)
    after_review = sum(row.get("ocr_status") == "OCR_REVIEW_REQUIRED" for row in data["questions"])
    after_ocr_verified = sum(row.get("ocr_status") == "OCR_MEDIUM_CONFIDENCE" for row in data["questions"])
    after_content_verified = sum(row.get("content_status") == "CONTENT_VERIFIED" for row in data["questions"])
    duplicate_occurrences = len(data["occurrences"]) - len({row.get("occurrence_id") for row in data["occurrences"]})
    duplicate_images = len(data["images"]) - len({row.get("image_id") for row in data["images"]})
    provenance_errors = db_validation.get("invalid_source_references", 0) + db_validation.get("missing_source_pages", 0)

    reconciliation = {
        "generated_at": now_iso(),
        "phase": "PHASE 5B.1",
        "authoritative_metadata": "official acquisition manifest, overridden only by four source-proven PDF-header corrections documented in metadata anomalies",
        "summary": source_context["summary"],
        "manifest_rows": manifest_detail,
        "canonical_sources": source_rows,
        "corrections": source_context["corrections"],
        "metadata_checks": metadata,
        "status": "PASS" if not metadata["unresolved_semantic_anomalies"] and metadata["automated_checks"]["required_field_failures"] == 0 and metadata["automated_checks"]["missing_local_pdfs"] == 0 and metadata["automated_checks"]["sha256_mismatches"] == 0 else "REVIEW_REQUIRED",
    }
    write_json(AUDIT / "jee_main_ocr_source_reconciliation.json", reconciliation)
    source_md = [
        "# JEE Main OCR source reconciliation — Phase 5B.1",
        "",
        f"Generated: {reconciliation['generated_at']}",
        "",
        f"Manifest rows selected: {source_context['summary']['manifest_rows_selected']}",
        f"Consolidated canonical sources: {source_context['summary']['consolidated_sources']}",
        f"Duplicate manifest rows collapsed: {source_context['summary']['duplicate_manifest_rows_collapsed']}",
        f"Successful sources: {source_context['summary']['successful_sources']}",
        f"Corrupt sources retained: {source_context['summary']['corrupt_sources']}",
        f"Partial sources retained: {source_context['summary']['partial_sources']}",
        "",
        "Every manifest row is represented in `jee_main_source_inventory.jsonl`; duplicate rows explicitly identify their canonical source row.",
        "",
        "## Evidence-backed corrections",
        "",
    ]
    if source_context["corrections"]:
        source_md.extend(["| prior source ID | effective source ID | evidence | action |", "|---|---|---|---|"])
        for correction in source_context["corrections"]:
            source_md.append(
                f"| `{correction['old_source_id']}` | `{correction['new_source_id']}` | {correction['evidence']} | {correction['action']} |"
            )
    else:
        source_md.append("No evidence-backed metadata corrections were required.")
    source_md.extend(
        [
            "",
            "## Provenance checks",
            "",
            f"Required-field failures: {metadata['automated_checks']['required_field_failures']}",
            f"Missing local PDFs: {metadata['automated_checks']['missing_local_pdfs']}",
            f"SHA-256 mismatches: {metadata['automated_checks']['sha256_mismatches']}",
            f"Filename/archive conflicts preserved and documented: {metadata['automated_checks']['filename_or_archive_conflict_count']}",
            "",
            "Original local paths and recorded SHA-256 values were preserved when semantic metadata was corrected.",
            "",
        ]
    )
    (AUDIT / "jee_main_ocr_source_reconciliation.md").write_text("\n".join(source_md), encoding="utf-8")
    anomaly_report = {
        "generated_at": reconciliation["generated_at"],
        "anomalies_found": len(source_context["corrections"]),
        "fixed": len(source_context["corrections"]),
        "unresolved": len(metadata["unresolved_semantic_anomalies"]),
        "corrections": source_context["corrections"],
        "filename_or_archive_conflicts_preserved": metadata["filename_or_archive_conflicts_preserved"],
        "automated_checks": metadata["automated_checks"],
    }
    write_json(AUDIT / "jee_main_metadata_anomalies.json", anomaly_report)
    (AUDIT / "jee_main_bilingual_reconciliation.md").write_text(
        "\n".join([
            "# JEE Main bilingual/source-language reconciliation",
            "",
            f"Generated: {reconciliation['generated_at']}",
            "",
            "The previous Phase 5B `bilingual_papers_total=77` counted both `English_Hindi` and Hindi-only PDFs. This report separates the manifest language labels.",
            "",
            "| category | source PDFs | recovered | unresolved |",
            "|---|---:|---:|---:|",
            f"| Explicitly bilingual (`English_Hindi`) | {bilingual['actual_bilingual_source_pdfs']} | {bilingual['actual_bilingual_recovered']} | {bilingual['actual_bilingual_unresolved']} |",
            f"| Hindi-only variant (`Hindi`) | {bilingual['hindi_variant_source_pdfs']} | {bilingual['hindi_variant_recovered']} | {bilingual['hindi_variant_unresolved']} |",
            f"| English-only (`English`) | {bilingual['source_language_counts'].get('English', 0)} | — | — |",
            "",
            f"The prior Phase 5A count of 13 refers to UNKNOWN format classifications, not bilingual-language PDFs. Those 13 records are therefore not numerically comparable to the current language counts.",
            "",
            "Unresolved sources remain explicitly represented in `sources.jsonl`; no OCR status was promoted because a source lacks recoverable question text or is corrupt/partial.",
            "",
        ]) + "\n",
        encoding="utf-8",
    )

    final_status = "OCR_REVIEW_RECONCILED" if reconciliation["status"] == "PASS" and placeholders["pass"] and options["pass"] and full_paper["pass"] and provenance_errors == 0 and duplicate_occurrences == 0 and duplicate_images == 0 else "OCR_CONTENT_REVIEW_REQUIRED"
    final_report = {
        "generated_at": reconciliation["generated_at"],
        "phase": "PHASE 5B.1",
        "final_status": final_status,
        "source_reconciliation": source_context["summary"],
        "metadata_anomalies": {"found": len(source_context["corrections"]), "fixed": len(source_context["corrections"]), "unresolved": len(metadata["unresolved_semantic_anomalies"]), "filename_conflicts_preserved": len(metadata["filename_or_archive_conflicts_preserved"])},
        "ocr_buckets": buckets,
        "before_after": {
            "question_occurrences_before": before_occurrences,
            "question_occurrences_after": len(data["occurrences"]),
            "ocr_verified_before": before_ocr_verified,
            "ocr_verified_after": after_ocr_verified,
            "content_verified_before": before_content_verified,
            "content_verified_after": after_content_verified,
            "review_required_before": before_review,
            "review_required_after": after_review,
        },
        "automatic_resolution": {"records_reprocessed": buckets["additional_targeted_reprocessing"], "records_promoted_to_verified": after_content_verified - before_content_verified, "no_false_promotions": after_content_verified == before_content_verified},
        "bilingual_reconciliation": bilingual,
        "placeholder_validation": placeholders,
        "option_validation": options,
        "full_paper_validation": full_paper,
        "partial_source_handling": [row.get("source_id") for row in source_rows if row.get("source_status") == "SOURCE_PARTIAL"],
        "corrupt_source_handling": [row.get("source_id") for row in source_rows if row.get("source_status") == "SOURCE_CORRUPT"],
        "sqlite_counts": sqlite_counts,
        "database_validation": db_validation,
        "duplicate_occurrence_ids": duplicate_occurrences,
        "duplicate_image_ids": duplicate_images,
        "provenance_errors": provenance_errors,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    write_json(AUDIT / "jee_main_ocr_review_reconciliation.json", final_report)
    md = [
        "# JEE Main OCR review reconciliation — Phase 5B.1", "", f"Generated: {final_report['generated_at']}", "", f"Final status: `{final_status}`", "",
        "## Source reconciliation", "", f"Manifest rows: {source_context['summary']['manifest_rows_selected']}", f"Consolidated sources: {source_context['summary']['consolidated_sources']}", f"Successful: {source_context['summary']['successful_sources']}", f"Corrupt: {source_context['summary']['corrupt_sources']}", f"Partial: {source_context['summary']['partial_sources']}", f"Duplicate manifest rows collapsed: {source_context['summary']['duplicate_manifest_rows_collapsed']}", "",
        "## OCR before/after", "", "| metric | before | after |", "|---|---:|---:|",
        f"| question occurrences | {before_occurrences} | {len(data['occurrences'])} |",
        f"| OCR verified (`OCR_MEDIUM_CONFIDENCE`) | {before_ocr_verified} | {after_ocr_verified} |",
        f"| content verified (`CONTENT_VERIFIED`) | {before_content_verified} | {after_content_verified} |",
        f"| review required | {before_review} | {after_review} |", "",
        "No additional OCR engine or source-image consensus pass was available for safe promotion. Existing Phase 5B pass-2 evidence was retained; uncertain text remains review-required.", "",
        "## Metadata anomalies", "", f"Found: {len(source_context['corrections'])}; fixed: {len(source_context['corrections'])}; unresolved semantic anomalies: {len(metadata['unresolved_semantic_anomalies'])}; preserved filename/archive conflicts: {len(metadata['filename_or_archive_conflicts_preserved'])}", "",
        "## Validation", "", f"Placeholders: questions={placeholders['question_placeholders']}, options={placeholders['option_placeholders']}", f"MCQ option validation: {options['mcq_occurrences_checked']} checked, {options['missing_abcd']} missing A-D", f"Full-paper validation: {'PASS' if full_paper['pass'] else 'FAIL'}", f"Provenance errors: {provenance_errors}", f"Duplicate occurrence IDs: {duplicate_occurrences}", f"Duplicate image IDs: {duplicate_images}", "",
        "## Scope boundary", "", "Phase 5C, solutions, taxonomy classification, and Supabase import were not started.", "",
    ]
    (AUDIT / "jee_main_ocr_review_reconciliation.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"final_status": final_status, "source_summary": source_context["summary"], "before_after": final_report["before_after"], "sqlite": sqlite_counts, "validation": db_validation}, indent=2))


if __name__ == "__main__":
    main()
