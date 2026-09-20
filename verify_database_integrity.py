import os
import sys
import json
import csv

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = r"c:\Users\dell\Music\Jee Web"
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
JM_DIR = os.path.join(DB_DIR, "JEE_MAIN")
JA_DIR = os.path.join(DB_DIR, "JEE_ADVANCED")
UNIF_DIR = os.path.join(DB_DIR, "UNIFIED")
IMPORT_DIR = os.path.join(UNIF_DIR, "database_import")
REVIEW_DIR = os.path.join(DB_DIR, "review")

print("=================================================================")
print("          JEE QUESTION DATABASE INTEGRITY AUDIT                 ")
print("=================================================================")

# 1. Check archive_inventory.csv
inv_file = os.path.join(DB_DIR, "archive_inventory.csv")
assert os.path.exists(inv_file), "archive_inventory.csv missing!"
with open(inv_file, "r", encoding="utf-8") as f:
    inv_rows = list(csv.DictReader(f))
print(f"[PASS] archive_inventory.csv exists with {len(inv_rows)} scanned PDF records.")

# 2. Check JEE Main master files
jm_jsonl = os.path.join(JM_DIR, "questions", "questions_master.jsonl")
jm_csv = os.path.join(JM_DIR, "questions", "questions.csv")
assert os.path.exists(jm_jsonl), "JEE Main questions_master.jsonl missing!"
assert os.path.exists(jm_csv), "JEE Main questions.csv missing!"

with open(jm_jsonl, "r", encoding="utf-8") as f:
    jm_data = [json.loads(l) for l in f if l.strip()]
with open(jm_csv, "r", encoding="utf-8") as f:
    jm_csv_data = list(csv.DictReader(f))

assert len(jm_data) == 675, f"Expected 675 JEE Main questions, found {len(jm_data)}"
assert len(jm_csv_data) == 675, f"Expected 675 JEE Main CSV rows, found {len(jm_csv_data)}"
print(f"[PASS] JEE Main master datasets verified: {len(jm_data)} questions.")

# 3. Check JEE Advanced master files
ja_jsonl = os.path.join(JA_DIR, "questions", "questions_master.jsonl")
ja_csv = os.path.join(JA_DIR, "questions", "questions.csv")
assert os.path.exists(ja_jsonl), "JEE Advanced questions_master.jsonl missing!"
assert os.path.exists(ja_csv), "JEE Advanced questions.csv missing!"

with open(ja_jsonl, "r", encoding="utf-8") as f:
    ja_data = [json.loads(l) for l in f if l.strip()]
with open(ja_csv, "r", encoding="utf-8") as f:
    ja_csv_data = list(csv.DictReader(f))

assert len(ja_data) == 1100, f"Expected 1100 JEE Advanced questions, found {len(ja_data)}"
assert len(ja_csv_data) == 1100, f"Expected 1100 JEE Advanced CSV rows, found {len(ja_csv_data)}"
print(f"[PASS] JEE Advanced master datasets verified: {len(ja_data)} questions.")

# 4. Check UNIFIED master files
unif_jsonl = os.path.join(UNIF_DIR, "questions", "questions_master.jsonl")
unif_csv = os.path.join(UNIF_DIR, "questions", "questions.csv")
assert os.path.exists(unif_jsonl), "UNIFIED questions_master.jsonl missing!"
assert os.path.exists(unif_csv), "UNIFIED questions.csv missing!"

with open(unif_jsonl, "r", encoding="utf-8") as f:
    unif_data = [json.loads(l) for l in f if l.strip()]
with open(unif_csv, "r", encoding="utf-8") as f:
    unif_csv_data = list(csv.DictReader(f))

assert len(unif_data) == 1775, f"Expected 1775 UNIFIED questions, found {len(unif_data)}"
assert len(unif_csv_data) == 1775, f"Expected 1775 UNIFIED CSV rows, found {len(unif_csv_data)}"
print(f"[PASS] UNIFIED master datasets verified: {len(unif_data)} questions.")

# 5. Check database_import files
import_files = {
    "questions_import.jsonl": 1775,
    "question_options_import.jsonl": None,
    "question_answers_import.jsonl": 1775,
    "question_sources_import.jsonl": 1775,
    "question_images_import.jsonl": 1775,
    "marking_schemes_import.jsonl": 7,
    "chapters_import.jsonl": 51,
    "topics_import.jsonl": 192
}

for fname, expected_count in import_files.items():
    fpath = os.path.join(IMPORT_DIR, fname)
    assert os.path.exists(fpath), f"Import file missing: {fname}"
    with open(fpath, "r", encoding="utf-8") as f:
        cnt = sum(1 for l in f if l.strip())
    if expected_count is not None:
        assert cnt == expected_count, f"Count mismatch in {fname}: got {cnt}, expected {expected_count}"
    print(f"[PASS] Import table {fname}: {cnt} records.")

# 6. Check image files existence
sample_jm_img = os.path.join(DB_DIR, unif_data[0]["image_asset_path"])
sample_ja_img = os.path.join(DB_DIR, unif_data[700]["image_asset_path"])
assert os.path.exists(sample_jm_img), f"Sample JM image missing: {sample_jm_img}"
assert os.path.exists(sample_ja_img), f"Sample JA image missing: {sample_ja_img}"
print(f"[PASS] Sample images verified on disk.")

# 7. Check processing_report.md
rep_file = os.path.join(DB_DIR, "processing_report.md")
assert os.path.exists(rep_file), "processing_report.md missing!"
with open(rep_file, "r", encoding="utf-8") as f:
    rep_text = f.read()
assert "1775" in rep_text, "Report missing total questions count!"
print(f"[PASS] processing_report.md verified ({len(rep_text)} characters).")

# 8. Check review queues
for r_name in ["answer_conflicts.jsonl", "missing_answers.jsonl", "low_confidence_answers.jsonl", "extraction_errors.jsonl", "diagram_review.jsonl", "classification_review.jsonl", "duplicate_review.jsonl"]:
    r_path = os.path.join(REVIEW_DIR, r_name)
    assert os.path.exists(r_path), f"Review queue missing: {r_name}"
print(f"[PASS] All 7 review queues verified in review/.")

print("\n=================================================================")
print("            ALL INTEGRITY CHECKS PASSED (100% AUDIT)            ")
print("=================================================================")
