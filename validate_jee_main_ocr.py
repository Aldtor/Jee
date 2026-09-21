"""Validate Phase 5B source-grounded JEE Main OCR outputs.

This validator is deliberately independent of the OCR writer.  It checks the
JSONL/SQLite graph, source/page/image provenance, and representative adversarial
and full-paper reconstructions without silently filling missing content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parent
FINAL = BASE / "JEE_QUESTION_DATABASE_FINAL"
JM = FINAL / "JEE_MAIN"
AUDIT = BASE / "audit"
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|PLACEHOLDER|DUMMY|LOREM|UNKNOWN_TEXT)\b", re.I)


def rows(name: str) -> list[dict[str, Any]]:
    path = JM / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_file(value: str | None) -> Path | None:
    if not value:
        return None
    path = BASE / value
    return path if path.exists() else None


def snippet(value: str | None, limit: int = 100) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def validate_graph(source_rows: list[dict[str, Any]], occurrence_rows: list[dict[str, Any]], option_rows: list[dict[str, Any]], image_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_map = {r.get("source_id"): r for r in source_rows}
    bad_sources: list[str] = []
    bad_hashes: list[str] = []
    for row in source_rows:
        path = BASE / str(row.get("source_pdf") or row.get("local_path") or "")
        if not path.exists():
            bad_sources.append(str(row.get("source_id")))
            continue
        expected = row.get("source_sha256")
        if expected and sha256(path) != expected:
            bad_hashes.append(str(row.get("source_id")))

    bad_occurrences: list[str] = []
    bad_pages: list[str] = []
    for row in occurrence_rows:
        sid = row.get("source_id")
        source = source_map.get(sid)
        if source is None:
            bad_occurrences.append(str(row.get("occurrence_id")))
            continue
        page_count = int(source.get("page_count") or source.get("total_pages") or 0)
        pages = row.get("source_pages") or ([row.get("source_page")] if row.get("source_page") else [])
        if not pages or any(int(page) < 1 or (page_count and int(page) > page_count) for page in pages):
            bad_pages.append(str(row.get("occurrence_id")))

    bad_images: list[str] = []
    for row in image_rows:
        sid = row.get("source_id")
        if sid and sid not in source_map:
            bad_images.append(str(row.get("image_id")))
        if row.get("image_path") and asset_file(row.get("image_path")) is None:
            bad_images.append(str(row.get("image_id")))

    occurrence_ids = [str(row.get("occurrence_id")) for row in occurrence_rows]
    image_ids = [str(row.get("image_id")) for row in image_rows]
    placeholder_questions = [str(row.get("occurrence_id")) for row in occurrence_rows if PLACEHOLDER_RE.search(str(row.get("question_text") or ""))]
    placeholder_options = [str(row.get("id")) for row in option_rows if PLACEHOLDER_RE.search(str(row.get("text") or ""))]
    return {
        "source_count": len(source_rows),
        "occurrence_count": len(occurrence_rows),
        "option_count": len(option_rows),
        "image_count": len(image_rows),
        "missing_sources": bad_sources,
        "source_hash_mismatches": bad_hashes,
        "invalid_occurrence_source_refs": bad_occurrences,
        "invalid_occurrence_pages": bad_pages,
        "invalid_image_refs": bad_images,
        "duplicate_occurrence_ids": sorted(k for k, v in Counter(occurrence_ids).items() if v > 1),
        "duplicate_image_ids": sorted(k for k, v in Counter(image_ids).items() if v > 1),
        "placeholder_questions": placeholder_questions,
        "placeholder_options": placeholder_options,
    }


def validate_sqlite() -> dict[str, Any]:
    db = FINAL / "jee_database.sqlite"
    if not db.exists():
        return {"database_missing": True}
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    fk = [list(row) for row in con.execute("PRAGMA foreign_key_check").fetchall()]
    counts: dict[str, int] = {}
    for table in ("sources", "questions", "question_occurrences", "options", "answers", "images"):
        try:
            counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            counts[table] = -1
    con.close()
    return {"database_missing": False, "foreign_key_violations": fk, "table_counts": counts}


def adversarial_review(source_map: dict[str, dict[str, Any]], occurrence_rows: list[dict[str, Any]], option_rows: list[dict[str, Any]], image_rows: list[dict[str, Any]]) -> dict[str, Any]:
    options_by_occ = defaultdict(list)
    for row in option_rows:
        options_by_occ[row.get("occurrence_id")].append(row)
    images_by_occ = defaultdict(list)
    for row in image_rows:
        images_by_occ[row.get("question_occurrence_id")].append(row)
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in occurrence_rows:
        by_year[str(row.get("year"))].append(row)
    years: dict[str, Any] = {}
    for year, items in sorted(by_year.items()):
        # Prioritize items most likely to expose OCR errors, then spread across
        # the paper sequence so this is not just a clean leading-page sample.
        ranked = sorted(items, key=lambda r: (r.get("ocr_status") != "OCR_REVIEW_REQUIRED", r.get("content_status") != "CONTENT_PARTIALLY_VERIFIED", int(r.get("question_number") or 0)))
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in ranked + sorted(items, key=lambda r: int(r.get("question_number") or 0)):
            oid = str(row.get("occurrence_id"))
            if oid in seen:
                continue
            selected.append(row)
            seen.add(oid)
            if len(selected) >= 20:
                break
        checks = []
        for row in selected:
            sid = row.get("source_id")
            source = source_map.get(sid, {})
            assets = images_by_occ.get(row.get("occurrence_id"), [])
            checks.append({
                "occurrence_id": row.get("occurrence_id"),
                "source_id": sid,
                "question_number": row.get("question_number"),
                "subject": row.get("subject"),
                "question_type": row.get("question_type"),
                "source_pages": row.get("source_pages"),
                "ocr_status": row.get("ocr_status"),
                "content_status": row.get("content_status"),
                "question_text": snippet(row.get("question_text")),
                "option_count": len(options_by_occ.get(row.get("occurrence_id"), [])),
                "asset_count": len(assets),
                "asset_paths": [a.get("image_path") for a in assets[:3]],
                "source_exists": bool(source),
            })
        years[year] = {
            "sample_size": len(checks),
            "required_minimum": 20,
            "pass": len(checks) >= 20 and all(c["source_exists"] and c["source_pages"] for c in checks),
            "sample": checks,
        }
    return years


def full_paper_review(source_rows: list[dict[str, Any]], occurrence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = defaultdict(list)
    for row in occurrence_rows:
        by_source[row.get("source_id")].append(row)
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in source_rows:
        items = by_source.get(source.get("source_id"), [])
        if items:
            by_year[str(source.get("year"))].append({"source": source, "items": items})
    output: dict[str, Any] = {}
    for year, candidates in sorted(by_year.items()):
        candidate = max(candidates, key=lambda x: len(x["items"]))
        source = candidate["source"]
        items = sorted(candidate["items"], key=lambda r: int(r.get("question_number") or 0))
        nums = [int(r.get("question_number")) for r in items if str(r.get("question_number", "")).isdigit()]
        duplicates = sorted(k for k, v in Counter(nums).items() if v > 1)
        missing = list(range(min(nums), max(nums) + 1)) if nums else []
        missing = [n for n in missing if n not in set(nums)]
        output[year] = {
            "source_id": source.get("source_id"),
            "source_pdf": source.get("source_pdf"),
            "source_status": source.get("source_status"),
            "question_count": len(items),
            "question_number_min": min(nums) if nums else None,
            "question_number_max": max(nums) if nums else None,
            "duplicate_question_numbers": duplicates,
            "missing_question_numbers_between_min_max": missing,
            "page_span": sorted({p for row in items for p in (row.get("source_pages") or [])}),
            "sequence_pass": bool(items) and not duplicates and not missing,
            "question_status_counts": dict(Counter(row.get("content_status") for row in items)),
        }
    return output


def write_reports(graph: dict[str, Any], sqlite: dict[str, Any], adversarial: dict[str, Any], full_papers: dict[str, Any]) -> None:
    AUDIT.mkdir(parents=True, exist_ok=True)
    result = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "graph": graph,
        "sqlite": sqlite,
        "adversarial_by_year": adversarial,
        "full_paper_by_year": full_papers,
    }
    (AUDIT / "jee_main_ocr_validation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    adv_lines = ["# JEE Main OCR adversarial review", "", "This report samples at least 20 reconstructed questions per available year, prioritizing review-required and partially verified records. It checks source references, source pages, options, and retained image evidence; it does not promote uncertain OCR to verified content.", ""]
    for year, data in adversarial.items():
        adv_lines += [f"## {year}", "", f"Sampled **{data['sample_size']}** questions; required minimum: **{data['required_minimum']}**; result: **{'PASS' if data['pass'] else 'REVIEW_REQUIRED'}**.", "", "| occurrence | subject | type | pages | OCR status | content status | options | assets |", "|---|---|---|---|---|---|---:|---:|"]
        for row in data["sample"]:
            adv_lines.append(f"| {row['occurrence_id']} | {row['subject']} | {row['question_type']} | {row['source_pages']} | {row['ocr_status']} | {row['content_status']} | {row['option_count']} | {row['asset_count']} |")
        adv_lines.append("")
    (AUDIT / "jee_main_ocr_adversarial_review.md").write_text("\n".join(adv_lines) + "\n", encoding="utf-8")
    full_lines = ["# JEE Main full-paper OCR reconstruction report", "", "For each available year, the source with the largest recovered question sequence is checked end-to-end for ordering, duplicate numbers, missing numbers between the observed minimum and maximum, page provenance, and status retention.", "", "| year | source | questions | sequence | status | page span |", "|---:|---|---:|---|---|---|"]
    for year, row in full_papers.items():
        full_lines.append(f"| {year} | {row['source_id']} | {row['question_count']} | {'PASS' if row['sequence_pass'] else 'REVIEW_REQUIRED'} | {row['source_status']} | {row['page_span']} |")
    full_lines += ["", "A sequence PASS means the reconstructed occurrence numbers are ordered without duplicates or internal gaps for the selected paper. It does not assert that OCR glyphs, mathematical notation, diagrams, or answer evidence are error-free; those remain governed by each record's OCR/content status and image provenance."]
    (AUDIT / "jee_main_full_ocr_reconstruction_report.md").write_text("\n".join(full_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("use --run")
    source_rows = rows("sources.jsonl")
    occurrence_rows = rows("question_occurrences.jsonl")
    option_rows = rows("options.jsonl")
    image_rows = rows("images.jsonl")
    source_map = {row.get("source_id"): row for row in source_rows}
    graph = validate_graph(source_rows, occurrence_rows, option_rows, image_rows)
    sqlite = validate_sqlite()
    adversarial = adversarial_review(source_map, occurrence_rows, option_rows, image_rows)
    full_papers = full_paper_review(source_rows, occurrence_rows)
    write_reports(graph, sqlite, adversarial, full_papers)
    print(json.dumps({"graph": {k: (len(v) if isinstance(v, list) else v) for k, v in graph.items()}, "sqlite": sqlite, "years": sorted(full_papers)}, indent=2))


if __name__ == "__main__":
    main()
