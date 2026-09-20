# JEE Previous Year Question Database & Official Archive

A production-grade, mathematically verified, multi-source validated question database and official PDF archive for **JEE Main (2019–2026)** and **JEE Advanced (2007–2026)**.

---

## 📊 Database Executive Summary

```
========================================================================================
                                JEE QUESTION DATABASE AUDIT
========================================================================================
Total Processed Questions               : 2,964
  - JEE Main Questions                  : 675 (225 Physics, 225 Chemistry, 225 Mathematics)
  - JEE Advanced Questions              : 2,289 (763 Physics, 763 Chemistry, 763 Mathematics)

Answer Verification Breakdown:
  - OFFICIAL_FINAL_KEY (Direct Match)   : 642 questions (21.7%)
  - OFFICIAL_SOURCE (Embedded Booklet)  : 732 questions (24.7%)
  - MULTI_SOURCE_VERIFIED (Consensus)   : 1,590 questions (53.6%)
  - INDEPENDENTLY_SOLVED                : 0 questions
  - CONFLICT                            : 0 questions
  - UNVERIFIED                          : 0 questions

Historical Marking Schemes              : 130 unique section scoring rules preserved
Canonical Syllabus Taxonomy             : 51 Chapters (18 Phy, 19 Chem, 14 Math)
                                          192 Topics (70 Phy, 68 Chem, 54 Math)
Diagrams Requiring Visual Assets        : 2,166 questions
Unnecessary Image Artifacts (Text-only) : 798 questions

Active Review Queue Items               : 839 items (in review/classification_review.jsonl)
========================================================================================
```

---

## 📁 Repository Structure

```
├── JEE_QUESTION_DATABASE/
│   ├── JEE_MAIN/
│   │   ├── questions/          # questions_master.jsonl & questions.csv
│   │   ├── answers/            # Formatted answer keys
│   │   └── images/             # Rendered question & figure crops
│   ├── JEE_ADVANCED/
│   │   ├── questions/          # questions_master.jsonl & questions.csv
│   │   ├── answers/            # Formatted answer keys
│   │   └── images/             # Rendered question cards and figures
│   └── UNIFIED/
│       ├── questions/          # Unified master files (2,964 items)
│       └── database_import/    # 8 Supabase-ready relational JSONL tables
│           ├── questions_import.jsonl
│           ├── question_options_import.jsonl
│           ├── question_answers_import.jsonl
│           ├── question_sources_import.jsonl
│           ├── question_images_import.jsonl
│           ├── marking_schemes_import.jsonl
│           ├── chapters_import.jsonl
│           └── topics_import.jsonl
│
├── audit/
│   ├── final_audit_report.md             # Comprehensive audit certification
│   ├── jee_main_coverage_matrix.csv      # 57 source PDFs audited by shift & status
│   ├── jee_advanced_coverage_matrix.csv  # 40 official papers (2007-2026) verified
│   ├── image_usage_report.csv            # Breakdown of genuine diagrams vs text artifacts
│   └── run_full_audit_and_rebuild.py     # End-to-end database pipeline script
│
├── review/
│   ├── classification_review.jsonl       # 839 items flagged for secondary topic refinement
│   ├── answer_conflicts.jsonl            # Conflict queue (0 items)
│   ├── missing_answers.jsonl             # Missing answer queue (0 items)
│   ├── diagram_review.jsonl              # Diagram review queue (0 items)
│   └── duplicate_review.jsonl            # Duplicate review queue (0 items)
│
├── JEE_Main_PYQ_Archive/                 # 57 Original official NTA PDFs
└── JEE_Advanced_PYQ_Archive/             # 70 Original official IIT PDFs
```

---

## 🔒 Answer Verification Taxonomy

Every question in the database is tagged with a strict verification level:
* **`OFFICIAL_FINAL_KEY`**: Answer traceable 1-to-1 to an official final answer key document (e.g., NTA compiled final answer key for JEE Main 2026 Session 2, and official final key for JEE Advanced 2026).
* **`OFFICIAL_SOURCE`**: Extracted directly from official question paper booklets containing embedded answers (JEE Advanced 2025, 2014, 2010, 2009, 2008, 2007).
* **`MULTI_SOURCE_VERIFIED`**: Verified across independent institutional solution consensus and mathematical derivation.
* **`CONFLICT`**: Discrepancies between official keys and independent derivations (routed to `review/answer_conflicts.jsonl`).
* **`UNVERIFIED`**: Questions where reliable answers cannot be established (routed to `review/missing_answers.jsonl`).

---

## 📐 Historical Marking Schemes

The test engine utilizes 130 specific section scoring schemes (`marking_schemes_import.jsonl`) reflecting historical rules for each year from 2007 through 2026:
* Single Correct Option: `+4/-1`, `+3/-1`, or `+3/0`
* Multiple Correct Options: `+4/-2` (with partial marks `+3`, `+2`, `+1`), `+4/-1`, or `+4/0`
* Numerical / Integer: `+4/0`, `+3/0`, or `+4/-1`
* Matrix Matching: `+8/-2`, `+8/-1`, `+6/0`, or `+3/-1`
* Comprehension / Paragraphs: `+4/-1`, `+4/-2`, or `+3/0`

---

## 🚀 Supabase / Database Import

The files in `JEE_QUESTION_DATABASE/UNIFIED/database_import/` are normalized and ready for direct relational database ingestion into PostgreSQL / Supabase:

```sql
-- Example Schema Mapping
CREATE TABLE questions (
    question_id VARCHAR(64) PRIMARY KEY,
    exam VARCHAR(32) NOT NULL,
    year INT NOT NULL,
    session VARCHAR(64),
    exam_date DATE,
    shift VARCHAR(32),
    paper VARCHAR(64),
    paper_number INT,
    subject VARCHAR(32) NOT NULL,
    chapter VARCHAR(128) NOT NULL,
    topic VARCHAR(128) NOT NULL,
    question_type VARCHAR(32) NOT NULL,
    question_text TEXT NOT NULL,
    marking_scheme_id VARCHAR(64) REFERENCES marking_schemes(marking_scheme_id),
    image_required BOOLEAN NOT NULL,
    exam_display VARCHAR(64),
    composite_display VARCHAR(128)
);
```

---

## 📜 Provenance & Official Source Restrictions

All documents have been extracted strictly from public official government and educational domains:
* NTA Official Portal: `jeemain.nta.nic.in`, `nta.ac.in`
* JEE Advanced Official Portal: `jeeadv.ac.in`
