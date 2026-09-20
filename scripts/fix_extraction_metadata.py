"""
scripts/fix_extraction_metadata.py

Post-processing script to fix known issues in extraction results:
1. Section B questions misclassified as MCQ -> NUMERICAL
2. Bilingual papers with 0 questions -> flag as NEEDS_REPARSE
3. Marks inference from section

Usage:
    python scripts/fix_extraction_metadata.py
"""
import json
import os
import sys
import re
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRACTION_DIR = os.path.join(REPO, "JEE_QUESTION_DATABASE_FINAL", "extraction")


def fix_question_types(result: dict) -> int:
    """Fix Section B questions misclassified as MCQ -> NUMERICAL."""
    fixes = 0
    for q in result.get("questions", []):
        section = q.get("section", "")
        q_type = q.get("question_type", "")
        
        # Section B in JEE Main is always numerical/SA
        if "Section B" in section and q_type == "MCQ":
            q["question_type"] = "NUMERICAL"
            fixes += 1
        
        # Fix marks based on question type
        if q.get("correct_marks") is None:
            if q["question_type"] == "MCQ":
                q["correct_marks"] = 4.0
                q["wrong_marks"] = 1.0
            else:
                q["correct_marks"] = 4.0
                q["wrong_marks"] = 0.0
    
    # Update summary
    if "summary" in result:
        mcq = sum(1 for q in result["questions"] if q.get("question_type") == "MCQ")
        num = sum(1 for q in result["questions"] if q.get("question_type") in ("NUMERICAL", "SA"))
        result["summary"]["mcq"] = mcq
        result["summary"]["numerical"] = num
    
    return fixes


def flag_empty_papers(result: dict) -> bool:
    """Flag papers with 0 questions for re-parsing."""
    if len(result.get("questions", [])) == 0:
        result["needs_reparse"] = True
        result["reparse_reason"] = "0 questions extracted — likely bilingual format with different text encoding"
        return True
    return False


def fix_duplicate_question_numbers(result: dict) -> int:
    """Detect and handle duplicate question numbers within a paper."""
    # In bilingual papers, each question appears twice (English + Hindi)
    # Deduplicate by keeping only unique question numbers
    seen = {}
    dupes = 0
    unique_questions = []
    
    for q in result.get("questions", []):
        key = (q.get("question_number"), q.get("nta_question_id"))
        if key in seen:
            dupes += 1
            continue
        seen[key] = True
        unique_questions.append(q)
    
    if dupes > 0:
        result["questions"] = unique_questions
        result["deduplicated_count"] = dupes
        
        # Update summary
        if "summary" in result:
            result["summary"]["total_questions"] = len(unique_questions)
            mcq = sum(1 for q in unique_questions if q.get("question_type") == "MCQ")
            num = sum(1 for q in unique_questions if q.get("question_type") in ("NUMERICAL", "SA"))
            result["summary"]["mcq"] = mcq
            result["summary"]["numerical"] = num
            result["summary"]["needs_review"] = sum(1 for q in unique_questions if q.get("needs_review"))
    
    return dupes


def main():
    print("=" * 60)
    print("FIX EXTRACTION METADATA")
    print("=" * 60)
    
    if not os.path.exists(EXTRACTION_DIR):
        print("ERROR: Extraction directory not found!")
        return 1
    
    files = [f for f in os.listdir(EXTRACTION_DIR) if f.endswith(".json") and f != "extraction_log.json"]
    print(f"Found {len(files)} extraction results")
    
    total_type_fixes = 0
    total_empty = 0
    total_deduped = 0
    
    for fname in sorted(files):
        fpath = os.path.join(EXTRACTION_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            result = json.load(f)
        
        # Apply fixes
        type_fixes = fix_question_types(result)
        is_empty = flag_empty_papers(result)
        deduped = fix_duplicate_question_numbers(result)
        
        total_type_fixes += type_fixes
        total_empty += (1 if is_empty else 0)
        total_deduped += deduped
        
        # Save if any fixes were made
        if type_fixes or is_empty or deduped:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            status = []
            if type_fixes: status.append(f"{type_fixes} type fixes")
            if is_empty: status.append("EMPTY")
            if deduped: status.append(f"{deduped} deduped")
            print(f"  {fname}: {', '.join(status)}")
    
    print(f"\nSummary:")
    print(f"  Question type fixes: {total_type_fixes}")
    print(f"  Empty papers: {total_empty}")
    print(f"  Deduplicated questions: {total_deduped}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
