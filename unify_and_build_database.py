import os
import sys
import json
import csv
import hashlib

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = r"c:\Users\dell\Music\Jee Web"
DB_DIR = os.path.join(BASE_DIR, "JEE_QUESTION_DATABASE")
JM_DIR = os.path.join(DB_DIR, "JEE_MAIN")
JA_DIR = os.path.join(DB_DIR, "JEE_ADVANCED")
UNIFIED_DIR = os.path.join(DB_DIR, "UNIFIED")
IMPORT_DIR = os.path.join(UNIFIED_DIR, "database_import")
REVIEW_DIR = os.path.join(UNIFIED_DIR, "review")

os.makedirs(os.path.join(UNIFIED_DIR, "questions"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "metadata"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "answers"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "sources"), exist_ok=True)
os.makedirs(os.path.join(UNIFIED_DIR, "reports"), exist_ok=True)
os.makedirs(IMPORT_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)

# 1. LOAD JEE MAIN QUESTIONS
print("Loading JEE Main questions...")
jm_questions = []
with open(os.path.join(JM_DIR, "questions", "questions_master.jsonl"), "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            jm_questions.append(json.loads(line))
print(f"Loaded {len(jm_questions)} JEE Main questions.")

# 2. LOAD JEE ADVANCED QUESTIONS
print("Loading JEE Advanced questions...")
ja_questions = []
with open(os.path.join(JA_DIR, "questions", "questions_master.jsonl"), "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            ja_questions.append(json.loads(line))
print(f"Loaded {len(ja_questions)} JEE Advanced questions.")

unified_questions = jm_questions + ja_questions
print(f"Total unified questions: {len(unified_questions)}")

# 3. DUPLICATE DETECTION & CANONICAL GROUPING
# Detect questions with identical text or option hashes
text_hash_map = {}
dup_groups = {}
dup_group_counter = 1

for q in unified_questions:
    # Normalize text for deduplication
    norm_text = q["question_text"].strip().lower()
    if len(norm_text) > 30:
        h = hashlib.md5(norm_text.encode("utf-8")).hexdigest()
        if h in text_hash_map:
            orig_qid = text_hash_map[h]
            if orig_qid not in dup_groups:
                grp_id = f"DUP_GRP_{dup_group_counter:04d}"
                dup_group_counter += 1
                dup_groups[orig_qid] = grp_id
            grp_id = dup_groups[orig_qid]
            q["duplicate_group_id"] = grp_id
            q["canonical_question_id"] = orig_qid
            q["is_duplicate"] = True
        else:
            text_hash_map[h] = q["question_id"]
            q["duplicate_group_id"] = None
            q["canonical_question_id"] = q["question_id"]
            q["is_duplicate"] = False
    else:
        q["duplicate_group_id"] = None
        q["canonical_question_id"] = q["question_id"]
        q["is_duplicate"] = False

# 4. WRITE UNIFIED MASTER DATASETS
unif_master_jsonl = os.path.join(UNIFIED_DIR, "questions", "questions_master.jsonl")
with open(unif_master_jsonl, "w", encoding="utf-8") as f:
    for q in unified_questions:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")
print(f"Saved {unif_master_jsonl}")

unif_master_csv = os.path.join(UNIFIED_DIR, "questions", "questions.csv")
csv_cols = [
    "question_id", "exam", "year", "session", "exam_date", "shift", "paper", "paper_number",
    "subject", "chapter", "topic", "question_type", "original_question_number",
    "correct_answer", "numerical_answer", "answer_status", "answer_confidence",
    "marks_correct", "marks_incorrect", "image_asset_path", "source_pdf", "source_page",
    "display_badge", "canonical_question_id", "duplicate_group_id"
]
with open(unif_master_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
    writer.writeheader()
    for q in unified_questions:
        writer.writerow(q)
print(f"Saved {unif_master_csv}")

# 5. WRITE UNIFIED ANSWERS & SOURCES
unif_answers = []
unif_sources = []

for q in unified_questions:
    unif_answers.append({
        "question_id": q["question_id"],
        "exam": q["exam"],
        "correct_answer": q["correct_answer"],
        "numerical_answer": q["numerical_answer"],
        "answer_status": q["answer_status"],
        "answer_confidence": q["answer_confidence"],
        "answer_source_name": q["answer_source_name"],
        "answer_source_url": q["answer_source_url"]
    })
    unif_sources.append({
        "question_id": q["question_id"],
        "exam": q["exam"],
        "year": q["year"],
        "session": q["session"],
        "date": q["exam_date"],
        "shift": q["shift"],
        "paper": q["paper"],
        "paper_number": q["paper_number"],
        "language": q["language"],
        "source_pdf": q["source_pdf"],
        "source_page": q["source_page"],
        "official_source": True
    })

with open(os.path.join(UNIFIED_DIR, "answers", "answers_master.jsonl"), "w", encoding="utf-8") as f:
    for a in unif_answers:
        f.write(json.dumps(a, ensure_ascii=False) + "\n")

with open(os.path.join(UNIFIED_DIR, "sources", "question_sources.jsonl"), "w", encoding="utf-8") as f:
    for s in unif_sources:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

# 6. GENERATE DATABASE IMPORT RELATIONAL TABLES
print("Generating database import relational files...")

# questions_import.jsonl
q_import_file = os.path.join(IMPORT_DIR, "questions_import.jsonl")
with open(q_import_file, "w", encoding="utf-8") as f:
    for q in unified_questions:
        row = {
            "question_id": q["question_id"],
            "exam": q["exam"],
            "year": q["year"],
            "session": q["session"],
            "exam_date": q["exam_date"],
            "shift": q["shift"],
            "paper": q["paper"],
            "subject": q["subject"],
            "chapter": q["chapter"],
            "topic": q["topic"],
            "question_type": q["question_type"],
            "original_question_number": q["original_question_number"],
            "question_text": q["question_text"],
            "marking_scheme_id": q["marking_scheme_id"],
            "difficulty": q["difficulty"],
            "canonical_question_id": q["canonical_question_id"],
            "display_badge": q["display_badge"]
        }
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

# question_options_import.jsonl
opt_import_file = os.path.join(IMPORT_DIR, "question_options_import.jsonl")
with open(opt_import_file, "w", encoding="utf-8") as f:
    for q in unified_questions:
        if q.get("options"):
            for opt_key, opt_text in q["options"].items():
                row = {
                    "question_id": q["question_id"],
                    "option_key": opt_key,
                    "option_text": opt_text,
                    "is_correct": (opt_key in str(q.get("correct_answer", "")))
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

# question_answers_import.jsonl
ans_import_file = os.path.join(IMPORT_DIR, "question_answers_import.jsonl")
with open(ans_import_file, "w", encoding="utf-8") as f:
    for a in unif_answers:
        f.write(json.dumps(a, ensure_ascii=False) + "\n")

# question_sources_import.jsonl
src_import_file = os.path.join(IMPORT_DIR, "question_sources_import.jsonl")
with open(src_import_file, "w", encoding="utf-8") as f:
    for s in unif_sources:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

# question_images_import.jsonl
img_import_file = os.path.join(IMPORT_DIR, "question_images_import.jsonl")
with open(img_import_file, "w", encoding="utf-8") as f:
    for q in unified_questions:
        if q.get("image_asset_path"):
            row = {
                "question_id": q["question_id"],
                "image_path": q["image_asset_path"],
                "image_type": "question_diagram",
                "is_primary": True
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

# 7. POPULATE REVIEW QUEUES
print("Generating review queues...")
review_queues = {
    "answer_conflicts.jsonl": [],
    "missing_answers.jsonl": [],
    "low_confidence_answers.jsonl": [],
    "extraction_errors.jsonl": [],
    "diagram_review.jsonl": [],
    "classification_review.jsonl": [],
    "duplicate_review.jsonl": []
}

for q in unified_questions:
    if q.get("answer_status") == "CONFLICT":
        review_queues["answer_conflicts.jsonl"].append(q)
    if not q.get("correct_answer") and q.get("numerical_answer") is None:
        review_queues["missing_answers.jsonl"].append(q)
    if q.get("answer_confidence") == "LOW":
        review_queues["low_confidence_answers.jsonl"].append(q)
    if not q.get("question_text") or len(q.get("question_text", "")) < 10:
        review_queues["extraction_errors.jsonl"].append(q)
    if q.get("diagram_review_required"):
        review_queues["diagram_review.jsonl"].append(q)
    if q.get("topic") == "Unknown" or not q.get("chapter"):
        review_queues["classification_review.jsonl"].append(q)
    if q.get("is_duplicate"):
        review_queues["duplicate_review.jsonl"].append(q)

for r_name, r_items in review_queues.items():
    r_path = os.path.join(REVIEW_DIR, r_name)
    with open(r_path, "w", encoding="utf-8") as f:
        for it in r_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"Review queue {r_name}: {len(r_items)} items.")

print("\nUnification and database import tables complete.")
