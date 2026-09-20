import os
import sys
import csv
import re
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = r"c:\Users\dell\Music\Jee Web"
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
MAIN_DIR = os.path.join(BASE_DIR, "JEE_Main_PYQ_Archive")
ADV_DIR = os.path.join(BASE_DIR, "JEE_Advanced_PYQ_Archive")

# 1. Create directory structure
dirs_to_create = [
    os.path.join(DB_DIR, "JEE_MAIN", sub)
    for sub in ["raw_reference", "questions", "answers", "solutions", "images", "metadata", "review", "reports"]
] + [
    os.path.join(DB_DIR, "JEE_ADVANCED", sub)
    for sub in ["raw_reference", "questions", "answers", "solutions", "images", "metadata", "review", "reports"]
] + [
    os.path.join(DB_DIR, "UNIFIED", sub)
    for sub in ["questions", "metadata", "answers", "sources", "database_import", "review", "reports"]
]

for d in dirs_to_create:
    os.makedirs(d, exist_ok=True)
print("Created all JEE_QUESTION_DATABASE subdirectories.")

# 2. Scan both archives to build archive_inventory.csv
inventory = []

# Scan JEE Main
print("Scanning JEE Main Archive...")
for root, _, files in os.walk(MAIN_DIR):
    for f in sorted(files):
        if not f.endswith(".pdf"):
            continue
        full_path = os.path.join(root, f)
        rel_path = os.path.relpath(full_path, MAIN_DIR)
        
        # Determine metadata from path and internal PDF inspection
        doc = pymupdf.open(full_path)
        page_count = len(doc)
        first_text = doc[0].get_text() if page_count > 0 else ""
        doc.close()
        
        exam = "JEE_MAIN"
        year_match = re.search(r"\b(20\d\d)\b", rel_path)
        year = year_match.group(1) if year_match else "Unknown"
        
        session_match = re.search(r"Session-?(\w+)", rel_path, re.IGNORECASE)
        session = f"Session {session_match.group(1)}" if session_match else ""
        
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", rel_path)
        exam_date = date_match.group(1) if date_match else ""
        if not exam_date:
            date_internal = re.search(r"Exam Date\s*:\s*(\d{2}[\.-]\d{2}[\.-]\d{4})", first_text, re.IGNORECASE)
            if date_internal:
                raw_d = date_internal.group(1).replace(".", "-")
                parts = raw_d.split("-")
                exam_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                
        shift_match = re.search(r"Shift-?(\d+)", rel_path, re.IGNORECASE)
        shift = f"Shift {shift_match.group(1)}" if shift_match else ""
        if not shift:
            shift_internal = re.search(r"Exam Shift\s*:\s*(First|Second|Shift-?I{1,3})", first_text, re.IGNORECASE)
            if shift_internal:
                s_val = shift_internal.group(1).lower()
                shift = "Shift 1" if ("first" in s_val or "shift-i" in s_val) else "Shift 2"

        paper_match = re.search(r"Paper-?(\d[AB]?)", rel_path, re.IGNORECASE)
        paper = f"Paper {paper_match.group(1)}" if paper_match else "Paper 1 (B.E./B.Tech)"
        paper_num = paper_match.group(1) if paper_match else "1"
        
        lang = "English"
        if "hindi" in rel_path.lower():
            lang = "Hindi"
            
        pdf_type = "Notice"
        is_ak = ""
        is_qp = ""
        
        if "Question-Paper" in rel_path or "Question-Papers" in rel_path:
            if page_count > 5:
                pdf_type = "Question Paper (Master)"
                is_qp = rel_path
            else:
                pdf_type = "Question Paper Display Notice"
        elif "Answer-Key" in rel_path or "Answer-Keys" in rel_path:
            pdf_type = "Final Answer Key"
            is_ak = rel_path
        elif "Notice" in rel_path or "Notices" in rel_path:
            pdf_type = "Challenge / Exam Notice"

        inventory.append({
            "exam": exam,
            "year": year,
            "session": session,
            "date": exam_date,
            "shift": shift,
            "paper": paper,
            "paper_number": paper_num,
            "language": lang,
            "pdf_type": pdf_type,
            "answer_key_file": is_ak,
            "question_paper_file": is_qp,
            "local_path": rel_path,
            "page_count": page_count,
            "file_size": os.path.getsize(full_path)
        })

# Scan JEE Advanced
print("Scanning JEE Advanced Archive...")
for root, _, files in os.walk(ADV_DIR):
    for f in sorted(files):
        if not f.endswith(".pdf"):
            continue
        full_path = os.path.join(root, f)
        rel_path = os.path.relpath(full_path, ADV_DIR)
        
        doc = pymupdf.open(full_path)
        page_count = len(doc)
        first_text = doc[0].get_text() if page_count > 0 else ""
        doc.close()
        
        exam = "JEE_ADVANCED"
        year_match = re.search(r"\b(20\d\d)\b", rel_path)
        year = year_match.group(1) if year_match else "Unknown"
        
        session = ""
        exam_date = ""
        shift = ""
        
        paper = "Paper 1" if "Paper-1" in rel_path else ("Paper 2" if "Paper-2" in rel_path else "AAT")
        paper_num = "1" if paper == "Paper 1" else ("2" if paper == "Paper 2" else "AAT")
        
        lang = "Bilingual"
        if "English" in rel_path:
            lang = "English"
        elif "Hindi" in rel_path:
            lang = "Hindi"
            
        pdf_type = "Question Paper"
        is_ak = ""
        is_qp = ""
        
        if "Answer-Key" in rel_path:
            pdf_type = "Final Answer Key" if "Final" in rel_path else "Provisional Answer Key"
            is_ak = rel_path
        else:
            pdf_type = "Question Paper"
            is_qp = rel_path

        inventory.append({
            "exam": exam,
            "year": year,
            "session": session,
            "date": exam_date,
            "shift": shift,
            "paper": paper,
            "paper_number": paper_num,
            "language": lang,
            "pdf_type": pdf_type,
            "answer_key_file": is_ak,
            "question_paper_file": is_qp,
            "local_path": rel_path,
            "page_count": page_count,
            "file_size": os.path.getsize(full_path)
        })

inv_csv_path = os.path.join(DB_DIR, "archive_inventory.csv")
fieldnames = [
    "exam", "year", "session", "date", "shift", "paper", "paper_number",
    "language", "pdf_type", "answer_key_file", "question_paper_file",
    "local_path", "page_count", "file_size"
]

with open(inv_csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in inventory:
        writer.writerow(row)

print(f"\nWrote archive inventory to {inv_csv_path} with {len(inventory)} entries.")
print(f"JEE Main entries: {len([r for r in inventory if r['exam'] == 'JEE_MAIN'])}")
print(f"JEE Advanced entries: {len([r for r in inventory if r['exam'] == 'JEE_ADVANCED'])}")
