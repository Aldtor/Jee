"""
scripts/build_source_inventory.py

Builds the authoritative source inventory from JEE_Main_PYQ_Archive.
Classifies each PDF by format type and extracts metadata.
Generates audit/jee_main_content_source_inventory.json and .md
"""
import json
import os
import hashlib
import re
import sys
from datetime import datetime
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(REPO, "JEE_Main_PYQ_Archive")
MANIFEST = os.path.join(ARCHIVE, "jee_main_official_paper_manifest.json")
AUDIT = os.path.join(REPO, "audit")

def detect_format(pdf_path, reader):
    """Detect PDF format type from text content."""
    try:
        text = ""
        for i in range(min(3, len(reader.pages))):
            text += reader.pages[i].extract_text() or ""
        
        # 2022 Session-2 format: uses "Item No:" and "Topic:" with tabular layout
        has_item_no = bool(re.search(r"Item No\s*:\s*\d+", text))
        has_topic = bool(re.search(r"Topic\s*:\s*\w+", text))
        has_question_label = bool(re.search(r"Question\s*:", text))
        has_abcd = bool(re.search(r"\bA\s*:\s*\n", text)) or bool(re.search(r"\bA:\s", text))
        
        if has_item_no and has_topic and has_question_label:
            return "CLEAN_TABULAR"
        
        # 2022 Session-1 format: uses "Q:N", "Topic Name:", and "ItemCode:"
        has_q_colon = bool(re.search(r"Q\s*:\s*\d+", text))
        has_topic_name = bool(re.search(r"Topic\s*Name\s*:", text))
        has_itemcode = bool(re.search(r"ItemCode\s*:", text))
        
        if has_q_colon and (has_topic_name or has_itemcode):
            return "JEE_MAIN_QP"
        
        # Recorded Response format: uses "Question Number:" with option IDs
        has_qn = bool(re.search(r"Question Number\s*:\s*\d+", text))
        has_options = bool(re.search(r"Options\s*:", text))
        has_option_ids = bool(re.search(r"\d{5,}\.\s", text))
        
        if has_qn and (has_options or has_option_ids):
            return "RECORDED_RESPONSE"
        
        return "UNKNOWN"
    except Exception:
        return "ERROR"


def detect_sections(reader):
    """Detect subject sections from text layer."""
    text = ""
    for i in range(min(len(reader.pages), 30)):
        text += (reader.pages[i].extract_text() or "") + "\n"
    
    sections = []
    
    # 2022 format: "Topic: Physics-Section A"
    topic_matches = re.findall(r"Topic\s*:\s*([^\n]+)", text)
    if topic_matches:
        seen = set()
        for t in topic_matches:
            t = t.strip()
            if t not in seen:
                seen.add(t)
                sections.append(t)
        return sections
    
    # Other formats: "Mathematics Section A", "Physics Section A"
    section_matches = re.findall(
        r"((?:Mathematics|Physics|Chemistry)\s*(?:Sec(?:tion)?\s*[A-Z])?)",
        text, re.IGNORECASE
    )
    if section_matches:
        seen = set()
        for s in section_matches:
            s = s.strip()
            if s not in seen:
                seen.add(s)
                sections.append(s)
        return sections
    
    return sections


def count_questions(reader, fmt):
    """Count questions detected in text layer (samples first 35 pages for speed)."""
    text = ""
    for i in range(min(len(reader.pages), 35)):
        try:
            text += (reader.pages[i].extract_text() or "") + "\n"
        except Exception:
            continue
    
    if fmt == "CLEAN_TABULAR":
        return len(re.findall(r"Item No\s*:\s*\d+", text))
    elif fmt == "JEE_MAIN_QP":
        return len(re.findall(r"Q\s*:\s*\d+", text))
    else:
        return len(re.findall(r"Question Number\s*:\s*\d+", text))


def detect_question_types(reader, fmt):
    """Detect question types from text layer."""
    text = ""
    for i in range(min(len(reader.pages), 30)):
        text += (reader.pages[i].extract_text() or "") + "\n"
    
    types = set(re.findall(r"Question Type\s*:\s*(\w+)", text))
    return list(types) if types else ["UNKNOWN"]


def main():
    import pypdf
    
    print("Building JEE Main Content Source Inventory...")
    print(f"Archive: {ARCHIVE}")
    
    with open(MANIFEST, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    # Filter to downloaded, non-duplicate Paper-I QPs
    downloaded = [
        r for r in manifest
        if r.get("download_status") == "AVAILABLE_AND_DOWNLOADED"
        and not r.get("is_duplicate")
    ]
    
    print(f"Manifest: {len(manifest)} total, {len(downloaded)} downloaded unique")
    
    inventory = []
    errors = []
    format_counts = defaultdict(int)
    
    for idx, rec in enumerate(downloaded):
        local_path = rec.get("local_path", "")
        if not local_path:
            errors.append(f"Record {idx}: no local_path")
            continue
        
        full_path = os.path.join(REPO, local_path) if not os.path.isabs(local_path) else local_path
        
        if not os.path.exists(full_path):
            errors.append(f"Record {idx}: file not found: {local_path}")
            continue
        
        try:
            reader = pypdf.PdfReader(full_path, strict=False)
            pages = len(reader.pages)
            fmt = detect_format(full_path, reader)
            sections = detect_sections(reader)
            q_count = count_questions(reader, fmt)
            q_types = detect_question_types(reader, fmt)
            
            # Compute SHA256
            with open(full_path, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            
            source_id = f"JM_{rec['year']}_S{rec.get('session','?').replace('Session-','')[-1]}_{rec.get('exam_date','').replace('-','')[4:]}_{rec.get('shift','?')}"
            
            entry = {
                "source_id": source_id,
                "year": rec["year"],
                "session": rec.get("session"),
                "exam_date": rec.get("exam_date"),
                "shift": rec.get("shift"),
                "language": rec.get("language", "English"),
                "paper_type": "Paper-I (B.E./B.Tech.)",
                "source_url": rec.get("qp_url") or rec.get("source_url_s3waas"),
                "local_path": local_path,
                "sha256": sha256,
                "page_count": pages,
                "format_type": fmt,
                "sections_detected": sections,
                "questions_detected": q_count,
                "question_types": q_types,
                "source_status": "VALID",
                "file_size_bytes": os.path.getsize(full_path),
            }
            
            inventory.append(entry)
            format_counts[fmt] += 1
            
            print(f"  [{idx + 1}/{len(downloaded)}] {source_id}: {fmt}, {pages}p, {q_count}q", flush=True)
                
        except Exception as e:
            errors.append(f"Record {idx} ({os.path.basename(local_path)}): {str(e)[:100]}")
            print(f"  [{idx + 1}/{len(downloaded)}] ERROR: {str(e)[:60]}", flush=True)
    
    print(f"\nProcessed: {len(inventory)} papers")
    print(f"Errors: {len(errors)}")
    print(f"Format distribution: {dict(format_counts)}")
    
    # Sort by year, date, shift
    inventory.sort(key=lambda x: (x["year"], x.get("exam_date", ""), x.get("shift", 0)))
    
    # Save JSON
    output = {
        "generated": datetime.now().isoformat(),
        "total_papers": len(inventory),
        "format_distribution": dict(format_counts),
        "by_year": {},
        "papers": inventory,
        "errors": errors,
    }
    
    by_year = defaultdict(int)
    for entry in inventory:
        by_year[entry["year"]] += 1
    output["by_year"] = dict(sorted(by_year.items()))
    
    json_path = os.path.join(AUDIT, "jee_main_content_source_inventory.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Written: {json_path}")
    
    # Generate markdown
    md = f"""# JEE Main Content Source Inventory

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Total Papers:** {len(inventory)}

---

## Format Distribution

| Format | Count | Years |
|--------|-------|-------|
"""
    format_years = defaultdict(set)
    for e in inventory:
        format_years[e["format_type"]].add(e["year"])
    for fmt, count in sorted(format_counts.items()):
        years = ", ".join(str(y) for y in sorted(format_years[fmt]))
        md += f"| {fmt} | {count} | {years} |\n"
    
    md += f"""
## Papers by Year

| Year | Papers | Format | Questions Detected |
|------|--------|--------|--------------------|
"""
    year_data = defaultdict(lambda: {"count": 0, "formats": set(), "questions": 0})
    for e in inventory:
        yd = year_data[e["year"]]
        yd["count"] += 1
        yd["formats"].add(e["format_type"])
        yd["questions"] += e["questions_detected"]
    
    for year in sorted(year_data):
        yd = year_data[year]
        fmts = ", ".join(sorted(yd["formats"]))
        md += f"| {year} | {yd['count']} | {fmts} | {yd['questions']} |\n"
    
    total_q = sum(yd["questions"] for yd in year_data.values())
    md += f"| **Total** | **{len(inventory)}** | | **{total_q}** |\n"
    
    md += f"""
## Detailed Paper List

| # | Source ID | Year | Date | Shift | Lang | Format | Pages | Qs |
|---|----------|------|------|-------|------|--------|-------|----|
"""
    for i, e in enumerate(inventory):
        md += f"| {i+1} | {e['source_id']} | {e['year']} | {e.get('exam_date','')} | {e.get('shift','')} | {e.get('language','')} | {e['format_type']} | {e['page_count']} | {e['questions_detected']} |\n"
    
    if errors:
        md += f"\n## Errors ({len(errors)})\n\n"
        for err in errors:
            md += f"- {err}\n"
    
    md_path = os.path.join(AUDIT, "jee_main_content_source_inventory.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Written: {md_path}")
    
    return 0 if not errors else 1

if __name__ == "__main__":
    sys.exit(main())
