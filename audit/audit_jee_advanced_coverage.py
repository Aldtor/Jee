import os
import sys
import csv
import json

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = r"c:\Users\dell\Music\Jee Web"
ARCHIVE_ADV = os.path.join(BASE_DIR, "JEE_Advanced_PYQ_Archive")
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
JA_DIR = os.path.join(DB_DIR, "JEE_ADVANCED")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")

# Load processed questions
ja_processed_file = os.path.join(JA_DIR, "questions", "questions_master.jsonl")
processed_years_papers = set()
if os.path.exists(ja_processed_file):
    with open(ja_processed_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                y = d.get("year")
                p = d.get("paper")
                if y and p:
                    processed_years_papers.add((int(y), p))

print(f"Loaded processed JEE Advanced (year, paper) combinations: {len(processed_years_papers)}")

matrix_rows = []

# Target years: 2007 through 2026
target_years = list(range(2007, 2027))

for year in target_years:
    y_dir = os.path.join(ARCHIVE_ADV, str(year))
    
    p1_found = "NOT FOUND"
    p2_found = "NOT FOUND"
    ak1_found = "NOT FOUND"
    ak2_found = "NOT FOUND"
    
    if os.path.exists(y_dir):
        # Check Paper 1
        p1_dir = os.path.join(y_dir, "Paper-1")
        if os.path.exists(p1_dir):
            for root, _, files in os.walk(p1_dir):
                for f in files:
                    if f.endswith(".pdf"):
                        if "Question-Paper" in root:
                            p1_found = "FOUND"
                        if "Answer-Key" in root:
                            ak1_found = "FOUND (Final Key)"
                            
        # Check Paper 2
        p2_dir = os.path.join(y_dir, "Paper-2")
        if os.path.exists(p2_dir):
            for root, _, files in os.walk(p2_dir):
                for f in files:
                    if f.endswith(".pdf"):
                        if "Question-Paper" in root:
                            p2_found = "FOUND"
                        if "Answer-Key" in root:
                            ak2_found = "FOUND (Final Key)"
                            
    # For historical years with embedded answers:
    if year in [2007, 2008, 2009, 2010, 2014]:
        ak1_found = "FOUND (Embedded in Paper 1 QP)"
        ak2_found = "FOUND (Embedded in Paper 2 QP)"
    elif year == 2025:
        ak1_found = "FOUND (Embedded Official Key)"
        ak2_found = "FOUND (Embedded Official Key)"
        
    p1_processed = "PROCESSED" if (year, "Paper 1") in processed_years_papers else "NOT PROCESSED"
    p2_processed = "PROCESSED" if (year, "Paper 2") in processed_years_papers else "NOT PROCESSED"
    
    matrix_rows.append({
        "year": str(year),
        "paper_1_found": p1_found,
        "paper_1_processed": p1_processed,
        "paper_2_found": p2_found,
        "paper_2_processed": p2_processed,
        "answer_key_1_found": ak1_found,
        "answer_key_2_found": ak2_found
    })

matrix_csv = os.path.join(AUDIT_DIR, "jee_advanced_coverage_matrix.csv")
fieldnames = [
    "year", "paper_1_found", "paper_1_processed", "paper_2_found", "paper_2_processed",
    "answer_key_1_found", "answer_key_2_found"
]

with open(matrix_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in matrix_rows:
        writer.writerow(row)

print(f"Wrote JEE Advanced coverage matrix to {matrix_csv} ({len(matrix_rows)} rows).")

# Print summary
all_p1_proc = all(r["paper_1_processed"] == "PROCESSED" for r in matrix_rows)
all_p2_proc = all(r["paper_2_processed"] == "PROCESSED" for r in matrix_rows)
print(f"All Paper 1s processed (2007-2026): {all_p1_proc}")
print(f"All Paper 2s processed (2007-2026): {all_p2_proc}")
