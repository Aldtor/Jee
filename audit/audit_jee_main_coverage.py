import os
import sys
import re
import csv
import json
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = r"c:\Users\dell\Music\Jee Web"
ARCHIVE_MAIN = os.path.join(BASE_DIR, "JEE_Main_PYQ_Archive")
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
JM_DIR = os.path.join(DB_DIR, "JEE_MAIN")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")

os.makedirs(AUDIT_DIR, exist_ok=True)

# Load existing processed questions
jm_processed_file = os.path.join(JM_DIR, "questions", "questions_master.jsonl")
processed_source_pdfs = set()
if os.path.exists(jm_processed_file):
    with open(jm_processed_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                src = data.get("source_pdf", "")
                if src:
                    processed_source_pdfs.add(os.path.normpath(src))

print(f"Loaded processed source PDFs: {len(processed_source_pdfs)}")

# Scan all original PDFs in JEE_Main_PYQ_Archive
main_files = []
for root, _, files in os.walk(ARCHIVE_MAIN):
    for f in sorted(files):
        if f.endswith(".pdf"):
            full_p = os.path.join(root, f)
            rel_p = os.path.relpath(full_p, ARCHIVE_MAIN)
            main_files.append((full_p, rel_p))

print(f"Total original PDFs in JEE_Main_PYQ_Archive: {len(main_files)}")

coverage_rows = []

for full_p, rel_p in main_files:
    # Inspect PDF
    doc = pymupdf.open(full_p)
    pages = len(doc)
    first_text = doc[0].get_text() if pages > 0 else ""
    doc.close()
    
    # Extract metadata
    year_m = re.search(r"\b(20\d\d)\b", rel_p)
    year = year_m.group(1) if year_m else "Unknown"
    
    sess_m = re.search(r"Session-?(\w+)", rel_p, re.IGNORECASE)
    session = f"Session {sess_m.group(1)}" if sess_m else "General"
    
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", rel_p)
    exam_date = date_m.group(1) if date_m else ""
    if not exam_date:
        d_int = re.search(r"Exam Date\s*:\s*(\d{2}[\.-]\d{2}[\.-]\d{4})", first_text)
        if d_int:
            raw_d = d_int.group(1).replace(".", "-")
            parts = raw_d.split("-")
            exam_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
            
    shift_m = re.search(r"Shift-?(\d+)", rel_p)
    shift = f"Shift {shift_m.group(1)}" if shift_m else ""
    if not shift:
        s_int = re.search(r"Exam Shift\s*:\s*(First|Second)", first_text)
        if s_int:
            shift = "Shift 1" if s_int.group(1) == "First" else "Shift 2"

    paper_m = re.search(r"Paper-?(\d[AB]?)", rel_p)
    paper = f"Paper {paper_m.group(1)}" if paper_m else "Paper 1 (B.E./B.Tech)"
    
    # Check if processed
    is_processed = False
    norm_rel = os.path.normpath(os.path.join("JEE_Main_PYQ_Archive", rel_p))
    for p_src in processed_source_pdfs:
        if norm_rel in p_src or rel_p in p_src:
            is_processed = True
            break
            
    # Determine document type & processing status
    if "Question-Paper" in rel_p or "Question-Papers" in rel_p:
        if pages > 5:
            doc_category = "Full Question Paper (Master)"
            status = "PROCESSED" if is_processed else "MISSING_PROCESSING"
            audit_note = "Full 75-question master paper processed with diagrams and answers."
        else:
            doc_category = "Question Paper Display Notice"
            status = "MANUAL_REVIEW_REQUIRED"
            audit_note = "NTA Public Notice announcing candidate response display on examinationservices.nic.in; does not contain raw question items."
    elif "Answer-Key" in rel_p or "Answer-Keys" in rel_p:
        doc_category = "Final Answer Key"
        status = "CATALOGED_KEY"
        audit_note = "Official tabular answer key containing Question IDs and Correct Option IDs; cataloged for reference."
    else:
        doc_category = "Official Notice"
        status = "MANUAL_REVIEW_REQUIRED"
        audit_note = "Informational examination bulletin/notice."

    coverage_rows.append({
        "year": year,
        "session": session,
        "date": exam_date,
        "shift": shift,
        "paper": paper,
        "source_pdf": rel_p,
        "page_count": pages,
        "document_category": doc_category,
        "processed": "true" if is_processed else "false",
        "audit_status": status,
        "audit_note": audit_note
    })

matrix_csv = os.path.join(AUDIT_DIR, "jee_main_coverage_matrix.csv")
fieldnames = [
    "year", "session", "date", "shift", "paper", "source_pdf", "page_count",
    "document_category", "processed", "audit_status", "audit_note"
]

with open(matrix_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in coverage_rows:
        writer.writerow(row)

print(f"\nWrote JEE Main coverage matrix to {matrix_csv} ({len(coverage_rows)} rows).")

# Summary breakdown
processed_count = sum(1 for r in coverage_rows if r["audit_status"] == "PROCESSED")
manual_review_count = sum(1 for r in coverage_rows if r["audit_status"] == "MANUAL_REVIEW_REQUIRED")
cataloged_keys = sum(1 for r in coverage_rows if r["audit_status"] == "CATALOGED_KEY")

print(f"Summary:")
print(f"  Total Original PDFs: {len(coverage_rows)}")
print(f"  Full Question Papers Processed: {processed_count}")
print(f"  Official Answer Key Tables Cataloged: {cataloged_keys}")
print(f"  Public Notices (Manual Review Required): {manual_review_count}")
