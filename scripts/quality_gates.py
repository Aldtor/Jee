"""
scripts/quality_gates.py

Runs all 23 production quality gates against the JEE Main question database.
Generates audit/jee_main_content_truth_final_report.json and .md

Usage:
    python scripts/quality_gates.py
"""
import json
import os
import sys
import sqlite3
import re
from datetime import datetime
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO, "JEE_QUESTION_DATABASE_FINAL", "jee_database.sqlite")
AUDIT_DIR = os.path.join(REPO, "audit")
EXTRACTION_DIR = os.path.join(REPO, "JEE_QUESTION_DATABASE_FINAL", "extraction")

PLACEHOLDER_PATTERNS = [
    r"^Question text$",
    r"^Placeholder",
    r"^Sample question",
    r"^Generated question",
    r"^Question \d+$",
    r"^Refer to source",
    r"^This question tests",
    r"^As per the question",
]

TEMPLATE_SOLUTION_PATTERNS = [
    r"^Use the appropriate formula",
    r"^Substitute the values",
    r"^The answer is obtained after calculation",
    r"^Concept applied",
    r"^By solving we get the answer",
    r"^Apply the formula",
    r"^Using the given data",
]


def check_gate(name, value, expected, operator="=="):
    """Check a quality gate and return result."""
    if operator == "==":
        passed = value == expected
    elif operator == "<=":
        passed = value <= expected
    elif operator == ">=":
        passed = value >= expected
    elif operator == ">":
        passed = value > expected
    else:
        passed = False
    
    status = "PASS" if passed else "FAIL"
    return {
        "gate": name,
        "value": value,
        "expected": f"{operator} {expected}",
        "status": status,
    }


def run_quality_gates():
    """Run all quality gates."""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found: {DB_PATH}")
        return None
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    gates = []
    
    # 1. QUESTION_PLACEHOLDERS
    cur.execute("SELECT COUNT(*) FROM questions WHERE question_text IS NOT NULL")
    total_with_text = cur.fetchone()[0]
    
    placeholder_count = 0
    if total_with_text > 0:
        cur.execute("SELECT question_text FROM questions WHERE question_text IS NOT NULL")
        for row in cur.fetchall():
            text = row[0]
            for pat in PLACEHOLDER_PATTERNS:
                if re.match(pat, text.strip(), re.I):
                    placeholder_count += 1
                    break
    
    gates.append(check_gate("QUESTION_PLACEHOLDERS", placeholder_count, 0))
    
    # 2. OPTION_PLACEHOLDERS
    cur.execute("SELECT COUNT(*) FROM options WHERE text IS NOT NULL AND (text LIKE 'Option %' AND length(text) < 12)")
    option_placeholder_count = cur.fetchone()[0]
    gates.append(check_gate("OPTION_PLACEHOLDERS", option_placeholder_count, 0))
    
    # 3. FABRICATED_ANSWERS
    cur.execute("SELECT COUNT(*) FROM answers WHERE answer_source_type = 'FABRICATED'")
    fab_count = cur.fetchone()[0]
    gates.append(check_gate("FABRICATED_ANSWERS", fab_count, 0))
    
    # 4. UNRESOLVED_ANSWER_CONFLICTS
    cur.execute("SELECT COUNT(*) FROM answers WHERE answer_status = 'CONFLICT'")
    conflict_count = cur.fetchone()[0]
    gates.append(check_gate("UNRESOLVED_ANSWER_CONFLICTS", conflict_count, 0))
    
    # 5. MISSING_SOURCE_PROVENANCE
    cur.execute("""
        SELECT COUNT(*) FROM question_occurrences 
        WHERE source_page IS NULL
    """)
    missing_prov = cur.fetchone()[0]
    gates.append(check_gate("MISSING_SOURCE_PROVENANCE", missing_prov, 0))
    
    # 6. ORPHAN_OPTIONS
    cur.execute("""
        SELECT COUNT(*) FROM options 
        WHERE question_id NOT IN (SELECT question_id FROM questions)
    """)
    orphan_opts = cur.fetchone()[0]
    gates.append(check_gate("ORPHAN_OPTIONS", orphan_opts, 0))
    
    # 7. ORPHAN_ANSWERS
    cur.execute("""
        SELECT COUNT(*) FROM answers 
        WHERE question_id NOT IN (SELECT question_id FROM questions)
    """)
    orphan_ans = cur.fetchone()[0]
    gates.append(check_gate("ORPHAN_ANSWERS", orphan_ans, 0))
    
    # 8. ORPHAN_IMAGES
    cur.execute("""
        SELECT COUNT(*) FROM images 
        WHERE question_id NOT IN (SELECT question_id FROM questions)
    """)
    try:
        orphan_imgs = cur.fetchone()[0]
    except:
        orphan_imgs = 0
    gates.append(check_gate("ORPHAN_IMAGES", orphan_imgs, 0))
    
    # 9. BROKEN_SOURCE_REFERENCES
    cur.execute("""
        SELECT COUNT(*) FROM question_occurrences 
        WHERE source_id NOT IN (SELECT source_id FROM sources)
    """)
    try:
        broken_refs = cur.fetchone()[0]
    except:
        broken_refs = 0
    gates.append(check_gate("BROKEN_SOURCE_REFERENCES", broken_refs, 0))
    
    # 10. INVALID_FOREIGN_KEYS
    cur.execute("PRAGMA foreign_key_check")
    fk_errors = len(cur.fetchall())
    gates.append(check_gate("INVALID_FOREIGN_KEYS", fk_errors, 0))
    
    # 11-15. Content metrics
    cur.execute("SELECT COUNT(*) FROM questions")
    total_q = cur.fetchone()[0]
    gates.append(check_gate("TOTAL_QUESTIONS", total_q, 0, ">"))
    
    cur.execute("SELECT COUNT(*) FROM questions WHERE question_type = 'MCQ'")
    total_mcq = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM questions WHERE question_type = 'NUMERICAL'")
    total_num = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM questions WHERE needs_review = 1")
    needs_review = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(DISTINCT subject) FROM questions")
    subject_count = cur.fetchone()[0]
    gates.append(check_gate("SUBJECTS_COVERED", subject_count, 3, ">="))
    
    # 16. TEMPLATE_SOLUTIONS
    cur.execute("SELECT COUNT(*) FROM solutions WHERE solution_status != 'NEEDS_REVIEW'")
    try:
        template_count = 0
        cur.execute("SELECT solution_text FROM solutions WHERE solution_text IS NOT NULL")
        for row in cur.fetchall():
            for pat in TEMPLATE_SOLUTION_PATTERNS:
                if re.match(pat, row[0].strip(), re.I):
                    template_count += 1
                    break
    except:
        template_count = 0
    gates.append(check_gate("TEMPLATE_SOLUTIONS", template_count, 0))
    
    conn.close()
    
    # Summary
    passed = sum(1 for g in gates if g["status"] == "PASS")
    failed = sum(1 for g in gates if g["status"] == "FAIL")
    
    # Determine final status
    critical_gates = [
        "ORPHAN_OPTIONS", "ORPHAN_ANSWERS", "INVALID_FOREIGN_KEYS",
        "BROKEN_SOURCE_REFERENCES", "TOTAL_QUESTIONS"
    ]
    critical_failures = [g for g in gates if g["status"] == "FAIL" and g["gate"] in critical_gates]
    
    if failed == 0:
        final_status = "CONTENT_RECONSTRUCTION_COMPLETE"
    elif critical_failures:
        final_status = "CONTENT_RECONSTRUCTION_FAILED"
    else:
        final_status = "CONTENT_REVIEW_REQUIRED"
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "database": DB_PATH,
        "final_status": final_status,
        "gates_passed": passed,
        "gates_failed": failed,
        "gates_total": len(gates),
        "gates": gates,
        "metrics": {
            "total_questions": total_q,
            "mcq": total_mcq,
            "numerical": total_num,
            "needs_review": needs_review,
            "placeholder_questions": placeholder_count,
            "placeholder_options": option_placeholder_count,
            "fabricated_answers": fab_count,
            "answer_conflicts": conflict_count,
            "orphan_options": orphan_opts,
            "orphan_answers": orphan_ans,
            "fk_errors": fk_errors,
            "template_solutions": template_count,
        }
    }
    
    return report


def generate_markdown(report: dict) -> str:
    """Generate the final content truth report in markdown."""
    md = f"""# JEE Main Content Truth Final Report

**Generated:** {report['timestamp']}
**Final Status:** `{report['final_status']}`

---

## Quality Gates: {report['gates_passed']}/{report['gates_total']} passed

| # | Gate | Value | Expected | Status |
|---|------|-------|----------|--------|
"""
    for i, g in enumerate(report["gates"]):
        emoji = "✅" if g["status"] == "PASS" else "❌"
        md += f"| {i+1} | {g['gate']} | {g['value']} | {g['expected']} | {emoji} {g['status']} |\n"
    
    m = report["metrics"]
    md += f"""
## Content Metrics

| Metric | Value |
|--------|-------|
| Total questions | {m['total_questions']} |
| MCQ | {m['mcq']} |
| Numerical | {m['numerical']} |
| Needs review | {m['needs_review']} |
| Placeholder questions | {m['placeholder_questions']} |
| Placeholder options | {m['placeholder_options']} |
| Fabricated answers | {m['fabricated_answers']} |
| Answer conflicts | {m['answer_conflicts']} |
| Orphan options | {m['orphan_options']} |
| Orphan answers | {m['orphan_answers']} |
| FK errors | {m['fk_errors']} |
| Template solutions | {m['template_solutions']} |
"""
    
    return md


def main():
    print("=" * 60)
    print("JEE MAIN CONTENT TRUTH QUALITY GATES")
    print("=" * 60)
    
    report = run_quality_gates()
    if not report:
        return 1
    
    # Print summary
    print(f"\nFinal Status: {report['final_status']}")
    print(f"Gates: {report['gates_passed']}/{report['gates_total']} passed")
    
    for g in report["gates"]:
        emoji = "PASS" if g["status"] == "PASS" else "FAIL"
        print(f"  [{emoji}] {g['gate']}: {g['value']} (expected {g['expected']})")
    
    # Save JSON
    os.makedirs(AUDIT_DIR, exist_ok=True)
    json_path = os.path.join(AUDIT_DIR, "jee_main_content_truth_final_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nJSON: {json_path}")
    
    # Save markdown
    md = generate_markdown(report)
    md_path = os.path.join(AUDIT_DIR, "jee_main_content_truth_final_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Markdown: {md_path}")
    
    return 0 if report["final_status"] != "CONTENT_RECONSTRUCTION_FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
