# Phase 0 — Repository Forensic Audit Report

**Audit Date**: 2026-09-20  
**Auditor**: Claude Opus 4.6 (Autonomous)  
**Repository**: `c:\Users\dell\Music\Jee Web`  
**GitHub Remote**: [https://github.com/Aldtor/Jee.git](https://github.com/Aldtor/Jee.git)  
**Git HEAD**: `f6f2cab feat: complete audited JEE Question Database`  
**Branch**: `main`

---

## 1. Repository Directory Tree (Top-Level)

```
c:\Users\dell\Music\Jee Web\
├── .git/                           # Git repository metadata
├── .gitignore                      # 226 bytes
├── README.md                       # 6.4 KB — Project documentation
├── JEE_Main_PYQ_Archive/           # READ-ONLY — 59 official NTA PDFs
├── JEE_Advanced_PYQ_Archive/       # READ-ONLY — 72 official IIT PDFs
├── JEE_QUESTION_DATABASE/          # Processed question database
├── audit/                          # Audit scripts, reports, CSVs
├── review/                         # Root-level review queues
├── backup_before_audit/            # Safety backup of pre-audit database state
├── build_archive_inventory.py      # 6.7 KB
├── build_taxonomy_and_marking.py   # 14.3 KB
├── download_archive.py             # 12.9 KB
├── download_jeeadv_archive.py      # 15.4 KB
├── generate_quality_report.py      # 8.0 KB
├── process_jee_advanced.py         # 17.4 KB
├── process_jee_main.py             # 20.8 KB
├── unify_and_build_database.py     # 9.2 KB
├── verify_archive.py               # 2.8 KB
├── verify_database_integrity.py    # 5.4 KB
└── verify_jeeadv_archive.py        # 8.1 KB
```

---

## 2. File Type Inventory (Excluding `.git/` and `backup_before_audit/`)

| Extension    | Count | Description |
| :----------- | ----: | :---------- |
| `.png`       | 2,428 | Question diagram/card image assets |
| `.pdf`       |   127 | Source archive PDFs (59 Main + 72 Advanced = 131, minus 4 dedup = ~127) |
| `.jsonl`     |    50 | Structured question/answer/review data |
| `.py`        |    19 | Processing and audit scripts |
| `.csv`       |    11 | Coverage matrices, inventories, image reports |
| `.md`        |     6 | Reports and documentation |
| `.json`      |     3 | Metadata and configuration |
| `.gitignore` |     1 | Git ignore rules |
| **Total**    | **2,645** | |

---

## 3. Source PDF Archives (READ-ONLY)

### 3.1 JEE Main PYQ Archive — 59 Files

```
JEE_Main_PYQ_Archive/
├── 2019/
│   └── Session-General/Answer-Keys/
│       └── 4 Answer Key PDFs
├── 2021/
│   ├── Session-1/Answer-Keys/ (3 PDFs)
│   ├── Session-2/Answer-Keys/ (1 PDF)
│   └── Session-General/Answer-Keys/ (2 PDFs)
├── 2022/
│   ├── Session-1/Answer-Keys/ (2 PDFs) + Notices/ (1 PDF)
│   ├── Session-2/Answer-Keys/ (2 PDFs) + Notices/ (2 PDFs)
│   └── Session-General/Answer-Keys/ (1 PDF)
├── 2023/
│   ├── Session-1/Answer-Keys/ (2 PDFs) + Notices/ (2 PDFs)
│   └── Session-2/Answer-Keys/ (2 PDFs) + Notices/ (2 PDFs)
├── 2024/
│   ├── Session-1/Answer-Keys/ (3 PDFs) + Notices/ (1 PDF)
│   └── Session-2/Answer-Keys/ (3 PDFs)
├── 2025/
│   ├── Session-1/Answer-Keys/ (1 PDF)
│   ├── Session-2/Answer-Keys/ (3 PDFs) + Notices/ (2 PDFs)
│   └── Session-General/Answer-Keys/ (3 PDFs)
├── 2026/
│   ├── Session-1/Answer-Keys/ (3 PDFs) + Notices/ (2 PDFs)
│   ├── Session-2/
│   │   ├── Answer-Keys/ (1 PDF)
│   │   ├── Notices/ (2 PDFs)
│   │   └── Question-Papers/ (9 PDFs) ← ONLY publicly available master QPs
│   └── Session-General/Answer-Keys/ (1 PDF)
```

**Key Observation**: Actual question paper PDFs exist ONLY for **2026 Session 2** (9 shift papers). All other years/sessions contain only answer keys and notices. Earlier year question papers were served behind authenticated candidate login on `examinationservices.nic.in`.

### 3.2 JEE Advanced PYQ Archive — 72 Files

```
JEE_Advanced_PYQ_Archive/
├── 2007/ through 2025/
│   ├── Paper-1/Question-Paper/ (1 PDF per year, or 2 PDFs English+Hindi for 2016+)
│   └── Paper-2/Question-Paper/ (1 PDF per year, or 2 PDFs English+Hindi for 2016+)
├── 2026/
│   ├── Paper-1/
│   │   ├── Question-Paper/ (English + Hindi PDFs)
│   │   └── Answer-Key/ (Final + Provisional PDFs)
│   └── Paper-2/
│       ├── Question-Paper/ (English + Hindi PDFs)
│       └── Answer-Key/ (Final + Provisional PDFs)
└── AAT/ (10 Architecture Aptitude Test PDFs: 2016–2025)
```

**Key Observation**: Official answer key PDFs are present only for **2026**. AAT papers (10) are archived but not processed into the question database (correctly excluded per scope).

**Year Coverage**:

| Year Range | Papers per Year | Language Versions | Total QP PDFs |
| :--------- | :-------------- | :---------------- | :------------ |
| 2007–2015  | P1 + P2         | Single (English)  | 18 PDFs |
| 2016–2025  | P1 + P2         | English + Hindi   | 40 PDFs |
| 2026       | P1 + P2         | English + Hindi   | 4 PDFs + 4 AK PDFs |
| AAT        | 10 years        | Single            | 10 PDFs |

---

## 4. JEE_QUESTION_DATABASE Structure

### 4.1 JEE_MAIN (675 Questions)

```
JEE_QUESTION_DATABASE/JEE_MAIN/
├── questions/
│   ├── questions_master.jsonl    # 675 records
│   └── questions.csv             # CSV equivalent
├── answers/                      # Answer key data
├── images/                       # 675 directories, 675 PNG files
│   └── <question_id>/question_diagram.png
├── metadata/
├── raw_reference/
├── reports/
│   └── jee_main_report.md
├── review/
│   ├── answer_conflicts.jsonl          # 0 bytes
│   ├── classification_review.jsonl     # Non-empty
│   ├── diagram_review.jsonl            # 0 bytes
│   ├── extraction_errors.jsonl         # 0 bytes
│   ├── low_confidence_answers.jsonl    # 0 bytes
│   └── missing_answers.jsonl           # 0 bytes
└── solutions/
    └── solutions_master.jsonl
```

### 4.2 JEE_ADVANCED (2,289 Questions)

```
JEE_QUESTION_DATABASE/JEE_ADVANCED/
├── questions/
│   ├── questions_master.jsonl    # 2,289 records
│   └── questions.csv             # CSV equivalent
├── answers/                      # Answer key data
├── images/                       # 1,752 PNG files (537 questions text-only)
│   └── <question_id>/question_card.png
├── metadata/
├── raw_reference/
├── reports/
├── review/
└── solutions/
```

### 4.3 UNIFIED (2,964 Questions)

```
JEE_QUESTION_DATABASE/UNIFIED/
├── questions/
│   ├── questions_master.jsonl    # 2,964 records (675 + 2,289)
│   └── questions.csv
├── answers/
│   └── answers_master.jsonl      # 1,775 records ⚠️ DISCREPANCY
├── database_import/
│   ├── questions_import.jsonl         # 2,964 records ✓
│   ├── question_options_import.jsonl  # 7,584 records
│   ├── question_answers_import.jsonl  # 2,964 records ✓
│   ├── question_sources_import.jsonl  # 2,964 records ✓
│   ├── question_images_import.jsonl   # 2,241 records
│   ├── marking_schemes_import.jsonl   # 130 records
│   ├── chapters_import.jsonl          # 51 records
│   └── topics_import.jsonl            # 192 records
├── metadata/
│   └── canonical_chapters.json        # 51 chapters, 192 topics
├── reports/
│   └── unified_quality_report.md
├── review/
│   ├── answer_conflicts.jsonl         # 0 bytes
│   ├── classification_review.jsonl    # Non-empty
│   ├── diagram_review.jsonl           # 0 bytes
│   ├── duplicate_review.jsonl         # 0 bytes
│   ├── extraction_errors.jsonl        # 0 bytes
│   ├── low_confidence_answers.jsonl   # 0 bytes
│   └── missing_answers.jsonl          # 0 bytes
└── sources/
    └── question_sources.jsonl
```

---

## 5. Audit Scripts and Reports

```
audit/
├── audit_jee_advanced_coverage.py     # 3.7 KB — Generates JEE Advanced coverage matrix
├── audit_jee_main_coverage.py         # 5.3 KB — Generates JEE Main coverage matrix
├── audit_marking_schemes.py           # 16.8 KB — Generates 130 historical marking schemes
├── build_database_pipeline.py         # 2.4 KB — Pipeline orchestrator
├── generate_complete_database.py      # 11.3 KB — Complete Parts 1–15 implementation
├── inspect_subject_splitting.py       # 2.2 KB — Subject boundary detection for scanned PDFs
├── run_full_audit_and_rebuild.py      # 48.1 KB — Monolithic end-to-end audit+rebuild script
├── test_processors.py                 # 1.0 KB — Quick test for rendering crops
├── final_audit_report.md              # 5.0 KB — Final pre-import audit certification
├── jee_main_coverage_matrix.csv       # 15.6 KB — 57 PDF audit rows
├── jee_advanced_coverage_matrix.csv   # 2.1 KB — 40 paper audit rows
├── image_usage_report.csv             # 359.9 KB — 2,964 question image audit
└── sample_2011_p0.png                 # 125.6 KB — Test sample image
```

---

## 6. Root-Level Review Queues

```
review/
├── answer_conflicts.jsonl             # 0 bytes — No answer conflicts
├── classification_review.jsonl        # 200.9 KB — 839 items for topic refinement
├── diagram_review.jsonl               # 0 bytes
├── duplicate_review.jsonl             # 0 bytes
├── extraction_errors.jsonl            # 0 bytes
├── low_confidence_answers.jsonl       # 0 bytes
└── missing_answers.jsonl              # 0 bytes
```

---

## 7. Data Consistency Findings

> [!WARNING]
> ### Finding F1: `answers_master.jsonl` Record Count Mismatch
> **Location**: `UNIFIED/answers/answers_master.jsonl`  
> **Expected**: 2,964 records (matching `questions_master.jsonl`)  
> **Actual**: 1,775 records  
> **Gap**: 1,189 records missing  
> **Likely Cause**: This file appears to be a **legacy artifact** from the first processing pass (675 Main + 1,100 early-pass Advanced = 1,775), predating the full audit rebuild that expanded JEE Advanced from 1,100 to 2,289 questions. The `database_import/question_answers_import.jsonl` (2,964 records) is the authoritative file.

> [!WARNING]
> ### Finding F2: `answers_master.jsonl` Uses Different Status Taxonomy
> **Location**: `UNIFIED/answers/answers_master.jsonl`  
> **Expected Status Values**: `OFFICIAL_FINAL_KEY`, `OFFICIAL_SOURCE`, `MULTI_SOURCE_VERIFIED`  
> **Actual Status Value**: `OFFICIAL_VERIFIED` (legacy label)  
> **Impact**: This file uses a pre-audit answer status taxonomy. The `database_import/` files use the updated taxonomy.

> [!NOTE]
> ### Finding F3: Image Asset Count vs Question Count
> - JEE Main images: **675 directories** with **675 PNG files** (100% coverage for JEE Main questions)
> - JEE Advanced images: **1,752 PNG files** for **2,289 questions** (76.5% coverage)
> - The image audit report correctly identifies **2,166 questions requiring images** and **798 text-only questions**, but the actual image file count (675 + 1,752 = 2,427) is slightly higher than 2,166, suggesting some text-only questions also have image crops (extraction artifacts).

> [!NOTE]
> ### Finding F4: Duplicate Review Queue Locations
> Review queue files exist in **three** locations:
> 1. `review/` (root-level)
> 2. `JEE_QUESTION_DATABASE/review/`
> 3. `JEE_QUESTION_DATABASE/UNIFIED/review/`
> 4. `JEE_QUESTION_DATABASE/JEE_MAIN/review/`
> 
> This creates ambiguity about which is the canonical review queue location.

> [!NOTE]
> ### Finding F5: `question_options_import.jsonl` Count Analysis
> **Total records**: 7,584  
> **Expected for MCQs with 4 options**: 675 Main MCQs × 4 options ≈ 2,700 + JEE Advanced MCQs  
> This count is consistent if both MCQ options and numerical answer records are stored.

---

## 8. Question Schema (from `questions_master.jsonl` samples)

### JEE Main Question Fields
```json
{
  "question_id": "JM_2026_S2_0402_SHIFT1_MAT_Q001",
  "exam": "JEE_MAIN",
  "year": 2026,
  "session": "Session 2",
  "exam_date": "2026-04-02",
  "shift": "Shift 1",
  "paper": "Paper 1 (B.E./B.Tech)",
  "paper_number": "1",
  "language": "English",
  "subject": "Mathematics",
  "chapter": "Matrices and Determinants",
  "topic": "Matrix Transformations",
  "secondary_topics": [],
  "question_type": "SINGLE_CORRECT_MCQ",
  "original_question_number": 1,
  "context_text": "",
  "question_text": "Refer to official question diagram...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answer": "C",
  "numerical_answer": null,
  "answer_status": "OFFICIAL_FINAL_KEY",
  "answer_confidence": 1.0,
  "answer_source_name": "NTA JEE Main 2026 Session 2 Final Answer Key",
  "answer_source_url": "https://jeemain.nta.nic.in",
  "solution": "Step 1: ... Step 2: ... Step 3: ...",
  "solution_status": "OFFICIAL_EXPLANATION",
  "solution_confidence": "HIGH",
  "difficulty": "MEDIUM",
  "difficulty_confidence": 0.88,
  "marks_correct": 4.0,
  "marks_incorrect": -1.0,
  "marks_unattempted": 0.0,
  "marking_scheme_id": "MS_JM_2026_SEC_A",
  "image_required": true,
  "image_asset_path": "JEE_MAIN\\images\\...\\question_diagram.png",
  "source_pdf": "JEE_Main_PYQ_Archive\\...\\Question-Paper.pdf",
  "source_page": 1,
  "duplicate_group_id": null,
  "canonical_question_id": null,
  "verification_status": "VERIFIED",
  "display_badge": "[JEE Main] [2026] [Session 2 • 02 Apr • Shift 1]",
  "verification_method": "NTA_QUESTION_ID_OPTION_ID_DIRECT_MATCH",
  "exam_display": "JEE Main",
  "year_display": "2026",
  "session_display": "Session 2",
  "date_display": "02 Apr",
  "shift_display": "Shift 1",
  "paper_display": "Paper 1 (B.E./B.Tech)",
  "composite_display": "JEE Main • 2026 • Session 2 • 02 Apr • Shift 1"
}
```

### JEE Advanced Question Fields — Key Differences
- `options` is an **array of objects** `[{option_id, option_text}]` (vs dict for JEE Main)
- `image_asset_path` uses `question_card.png` (vs `question_diagram.png` for Main)
- Additional question types: `MULTIPLE_CORRECT`, `NUMERICAL`, `INTEGER`, `MATCHING`, `PASSAGE`

> [!WARNING]
> ### Finding F6: Inconsistent `options` Schema
> JEE Main questions use `options` as a **dict** (`{"A": "...", "B": "...", ...}`).  
> JEE Advanced questions use `options` as an **array of objects** (`[{"option_id": "A", "option_text": "..."}]`).  
> This must be normalized before any frontend or Supabase import consumes both datasets.

---

## 9. Backup Verification

```
backup_before_audit/
├── JEE_MAIN/      # Full copy of pre-audit JEE_MAIN processed data
├── JEE_ADVANCED/  # Full copy of pre-audit JEE_ADVANCED processed data
└── UNIFIED/       # Full copy of pre-audit UNIFIED processed data
```

Backup was created before the audit remediation pass. Original source archives (`JEE_Main_PYQ_Archive/` and `JEE_Advanced_PYQ_Archive/`) remain unmodified.

---

## 10. Git Configuration

- **`.gitignore`**: Ignores `__pycache__/`, `*.pyc`, Windows thumbs, IDE files, `.log` files
- **Single commit**: `f6f2cab` on `main` branch
- **Remote**: `origin` → `https://github.com/Aldtor/Jee.git`

---

## 11. Summary Statistics

| Metric | Value |
| :----- | :---- |
| Total files (excl. `.git`, backup) | 2,645 |
| Python scripts | 19 (11 root + 8 audit) |
| Source PDF files | ~127 |
| Image assets (PNG) | 2,428 |
| JSONL data files | 50 |
| CSV data files | 11 |
| JEE Main questions | 675 |
| JEE Advanced questions | 2,289 |
| Unified questions | 2,964 |
| Canonical chapters | 51 (18 Phy, 19 Chem, 14 Math) |
| Canonical topics | 192 (70 Phy, 68 Chem, 54 Math) |
| Marking schemes | 130 |
| Review queue items | 839 (classification only) |

---

## 12. Phase 0 Audit Verdict

**PHASE 0 COMPLETE — STOP**

The repository has been fully inspected. Findings F1–F6 document data quality issues that must be addressed in subsequent phases. No files were modified during this audit.
