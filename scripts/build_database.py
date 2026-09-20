"""
scripts/build_database.py

Builds the normalized production database from extraction results.
Creates JSONL files + SQLite database with FK enforcement.

Usage:
    python scripts/build_database.py
"""
import json
import os
import sys
import sqlite3
import hashlib
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO, "JEE_QUESTION_DATABASE_FINAL")
EXTRACTION_DIR = os.path.join(OUTPUT_DIR, "extraction")
MAIN_DIR = os.path.join(OUTPUT_DIR, "JEE_MAIN")
DB_PATH = os.path.join(OUTPUT_DIR, "jee_database.sqlite")

# Load taxonomy
CHAPTERS_FILE = os.path.join(OUTPUT_DIR, "JEE_MAIN", "chapters.jsonl")
TOPICS_FILE = os.path.join(OUTPUT_DIR, "JEE_MAIN", "topics.jsonl")


def load_extraction_results() -> List[Dict]:
    """Load all per-paper extraction results."""
    results = []
    if not os.path.exists(EXTRACTION_DIR):
        return results
    
    for fname in sorted(os.listdir(EXTRACTION_DIR)):
        if fname.endswith(".json") and fname != "extraction_log.json":
            fpath = os.path.join(EXTRACTION_DIR, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                results.append(data)
    
    return results


def generate_question_id(year, session, date, shift, subject, q_num) -> str:
    """Generate a deterministic question ID."""
    session_num = ""
    if session:
        if "1" in str(session):
            session_num = "S1"
        elif "2" in str(session):
            session_num = "S2"
        else:
            session_num = str(session)[:2]
    
    date_str = str(date).replace("-", "")[4:] if date else "0000"
    
    subj_abbr = {
        "Physics": "PHY",
        "Chemistry": "CHE",
        "Mathematics": "MAT",
    }.get(subject, "UNK")
    
    return f"JM_{year}_{session_num}_{date_str}_SHIFT{shift}_{subj_abbr}_Q{q_num:03d}"


def compute_canonical_hash(question_text: str, options: List[str]) -> str:
    """Compute a canonical hash for deduplication."""
    # Normalize text
    text = (question_text or "").strip().lower()
    opt_text = "|".join(sorted((o or "").strip().lower() for o in options))
    combined = f"{text}|||{opt_text}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def build_sources(results: List[Dict]) -> List[Dict]:
    """Build sources.jsonl from extraction results."""
    sources = []
    for r in results:
        meta = r.get("metadata", {})
        source = {
            "source_id": f"JM_{meta.get('year', 0)}_{meta.get('session', '')}_{meta.get('exam_date', '')}_{meta.get('shift', '')}",
            "exam": "JEE_MAIN",
            "year": meta.get("year"),
            "session": meta.get("session"),
            "exam_date": meta.get("exam_date"),
            "shift": meta.get("shift"),
            "language": meta.get("language"),
            "paper_type": meta.get("paper_type"),
            "source_pdf": r.get("source_path"),
            "source_sha256": r.get("source_sha256"),
            "total_pages": r.get("total_pages"),
            "format_type": r.get("format_type"),
            "questions_extracted": r.get("summary", {}).get("total_questions", 0),
        }
        sources.append(source)
    return sources


def build_questions_and_options(results: List[Dict]) -> tuple:
    """Build questions, options, answers, question_occurrences from extraction results."""
    questions = []
    question_occurrences = []
    options_list = []
    answers_list = []
    
    for r in results:
        meta = r.get("metadata", {})
        year = meta.get("year", 0)
        session = meta.get("session", "")
        exam_date = meta.get("exam_date", "")
        shift = meta.get("shift", 0)
        language = meta.get("language", "English")
        
        for q_data in r.get("questions", []):
            q_num = q_data.get("question_number", 0)
            subject = q_data.get("subject", "Unknown")
            q_type = q_data.get("question_type", "MCQ")
            
            q_id = generate_question_id(year, session, exam_date, shift, subject, q_num)
            
            # Compute canonical hash
            q_text = q_data.get("question_text") or ""
            opt_texts = [o.get("text", "") or "" for o in q_data.get("options", [])]
            canonical_hash = compute_canonical_hash(q_text, opt_texts)
            
            question = {
                "question_id": q_id,
                "canonical_hash": canonical_hash,
                "exam": "JEE_MAIN",
                "question_type": q_type,
                "subject": subject,
                "question_text": q_text if q_text else None,
                "question_image_path": q_data.get("question_image_path"),
                "nta_question_id": q_data.get("nta_question_id"),
                "extraction_method": q_data.get("extraction_method"),
                "extraction_confidence": q_data.get("extraction_confidence", 0),
                "needs_review": q_data.get("needs_review", False),
                "review_reason": q_data.get("review_reason"),
            }
            questions.append(question)
            
            # Question occurrence
            occurrence = {
                "occurrence_id": f"{q_id}_OCC1",
                "question_id": q_id,
                "source_id": f"JM_{year}_{session}_{exam_date}_{shift}",
                "year": year,
                "session": session,
                "exam_date": exam_date,
                "shift": shift,
                "language": language,
                "question_number": q_num,
                "subject": subject,
                "section": q_data.get("section"),
                "source_page": q_data.get("source_page"),
                "correct_marks": q_data.get("correct_marks"),
                "wrong_marks": q_data.get("wrong_marks"),
            }
            question_occurrences.append(occurrence)
            
            # Options
            for opt in q_data.get("options", []):
                option = {
                    "id": f"{q_id}_OPT{opt.get('option_index', 0)}",
                    "question_id": q_id,
                    "option_index": opt.get("option_index"),
                    "label": opt.get("label"),
                    "text": opt.get("text"),
                    "image_path": opt.get("image_path"),
                    "option_nta_id": opt.get("option_nta_id"),
                    "extraction_confidence": opt.get("extraction_confidence", 0),
                }
                options_list.append(option)
            
            # Answer (placeholder — will be populated by verify_answers.py)
            answer = {
                "question_id": q_id,
                "correct_answer": None,
                "numerical_answer": None,
                "answer_status": "NEEDS_VERIFICATION",
                "answer_source_type": "NEEDS_REVIEW",
                "answer_confidence": 0.0,
            }
            answers_list.append(answer)
    
    return questions, question_occurrences, options_list, answers_list


def write_jsonl(data: List[Dict], filepath: str):
    """Write a list of dicts as JSONL."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Written: {os.path.basename(filepath)} ({len(data)} records)")


def build_sqlite(questions, occurrences, options, answers, sources):
    """Build SQLite database with FK enforcement."""
    if os.path.exists(DB_PATH):
        os.rename(DB_PATH, DB_PATH + ".bak")
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    cur = conn.cursor()
    
    # Create tables
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            exam TEXT NOT NULL,
            year INTEGER,
            session TEXT,
            exam_date TEXT,
            shift INTEGER,
            language TEXT,
            paper_type TEXT,
            source_pdf TEXT,
            source_sha256 TEXT,
            total_pages INTEGER,
            format_type TEXT,
            questions_extracted INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS questions (
            question_id TEXT PRIMARY KEY,
            canonical_hash TEXT,
            exam TEXT NOT NULL,
            question_type TEXT,
            subject TEXT,
            question_text TEXT,
            question_image_path TEXT,
            nta_question_id TEXT,
            extraction_method TEXT,
            extraction_confidence REAL,
            needs_review INTEGER DEFAULT 0,
            review_reason TEXT
        );
        
        CREATE TABLE IF NOT EXISTS question_occurrences (
            occurrence_id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL REFERENCES questions(question_id),
            source_id TEXT REFERENCES sources(source_id),
            year INTEGER,
            session TEXT,
            exam_date TEXT,
            shift INTEGER,
            language TEXT,
            question_number INTEGER,
            subject TEXT,
            section TEXT,
            source_page INTEGER,
            correct_marks REAL,
            wrong_marks REAL
        );
        
        CREATE TABLE IF NOT EXISTS options (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL REFERENCES questions(question_id),
            option_index INTEGER,
            label TEXT,
            text TEXT,
            image_path TEXT,
            option_nta_id TEXT,
            extraction_confidence REAL
        );
        
        CREATE TABLE IF NOT EXISTS answers (
            question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
            correct_answer TEXT,
            numerical_answer REAL,
            answer_status TEXT,
            answer_source_type TEXT,
            answer_confidence REAL
        );
        
        CREATE TABLE IF NOT EXISTS solutions (
            question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
            solution_text TEXT,
            solution_status TEXT DEFAULT 'NEEDS_REVIEW',
            solution_method TEXT
        );
        
        CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY,
            question_id TEXT REFERENCES questions(question_id),
            image_type TEXT,
            image_path TEXT,
            source_pdf TEXT,
            source_page INTEGER,
            width INTEGER,
            height INTEGER,
            sha256 TEXT
        );
        
        CREATE TABLE IF NOT EXISTS chapters (
            chapter_id TEXT PRIMARY KEY,
            subject TEXT,
            chapter_name TEXT,
            display_order INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS topics (
            topic_id TEXT PRIMARY KEY,
            chapter_id TEXT REFERENCES chapters(chapter_id),
            topic_name TEXT,
            display_order INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS question_topics (
            question_id TEXT REFERENCES questions(question_id),
            topic_id TEXT REFERENCES topics(topic_id),
            classification_confidence REAL,
            classification_status TEXT DEFAULT 'NEEDS_REVIEW',
            PRIMARY KEY (question_id, topic_id)
        );
        
        CREATE TABLE IF NOT EXISTS marking_schemes (
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
    """)
    
    # Insert data
    for src in sources:
        cur.execute("""INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (src["source_id"], src["exam"], src["year"], src["session"],
             src["exam_date"], src["shift"], src["language"], src["paper_type"],
             src["source_pdf"], src["source_sha256"], src["total_pages"],
             src["format_type"], src["questions_extracted"]))
    
    for q in questions:
        cur.execute("""INSERT OR REPLACE INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (q["question_id"], q["canonical_hash"], q["exam"], q["question_type"],
             q["subject"], q["question_text"], q["question_image_path"],
             q["nta_question_id"], q["extraction_method"], q["extraction_confidence"],
             1 if q["needs_review"] else 0, q["review_reason"]))
    
    for occ in occurrences:
        cur.execute("""INSERT OR REPLACE INTO question_occurrences VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (occ["occurrence_id"], occ["question_id"], occ["source_id"],
             occ["year"], occ["session"], occ["exam_date"], occ["shift"],
             occ["language"], occ["question_number"], occ["subject"],
             occ["section"], occ["source_page"], occ["correct_marks"], occ["wrong_marks"]))
    
    for opt in options:
        cur.execute("""INSERT OR REPLACE INTO options VALUES (?,?,?,?,?,?,?,?)""",
            (opt["id"], opt["question_id"], opt["option_index"], opt["label"],
             opt["text"], opt["image_path"], opt["option_nta_id"],
             opt["extraction_confidence"]))
    
    for ans in answers:
        cur.execute("""INSERT OR REPLACE INTO answers VALUES (?,?,?,?,?,?)""",
            (ans["question_id"], ans["correct_answer"], ans["numerical_answer"],
             ans["answer_status"], ans["answer_source_type"], ans["answer_confidence"]))
    
    conn.commit()
    
    # Verify
    for table in ["sources", "questions", "question_occurrences", "options", "answers"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"  SQLite {table}: {count} rows")
    
    # FK check
    cur.execute("PRAGMA foreign_key_check")
    fk_errors = cur.fetchall()
    if fk_errors:
        print(f"  WARNING: {len(fk_errors)} FK violations!")
    else:
        print(f"  FK check: PASS")
    
    conn.close()


def main():
    print("=" * 60)
    print("JEE MAIN DATABASE BUILDER")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Load extraction results
    results = load_extraction_results()
    print(f"Loaded {len(results)} extraction results")
    
    if not results:
        print("ERROR: No extraction results found!")
        return 1
    
    # Build data
    print("\nBuilding data structures...")
    sources = build_sources(results)
    questions, occurrences, options, answers = build_questions_and_options(results)
    
    print(f"  Sources: {len(sources)}")
    print(f"  Questions: {len(questions)}")
    print(f"  Occurrences: {len(occurrences)}")
    print(f"  Options: {len(options)}")
    print(f"  Answers: {len(answers)}")
    
    # Write JSONL
    print("\nWriting JSONL files...")
    os.makedirs(MAIN_DIR, exist_ok=True)
    write_jsonl(sources, os.path.join(MAIN_DIR, "sources.jsonl"))
    write_jsonl(questions, os.path.join(MAIN_DIR, "questions.jsonl"))
    write_jsonl(occurrences, os.path.join(MAIN_DIR, "question_occurrences.jsonl"))
    write_jsonl(options, os.path.join(MAIN_DIR, "options.jsonl"))
    write_jsonl(answers, os.path.join(MAIN_DIR, "answers.jsonl"))
    
    # Build SQLite
    print("\nBuilding SQLite database...")
    build_sqlite(questions, occurrences, options, answers, sources)
    
    print(f"\nDatabase built: {DB_PATH}")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
