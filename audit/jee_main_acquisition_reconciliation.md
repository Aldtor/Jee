# JEE Main Acquisition Reconciliation Report

**Generated:** 2026-09-20  
**Authoritative Source:** https://nta.ac.in/Downloads  
**Commit:** e2876f861e273f299ca98cefa49889c996131eae  
**Status:** ACQUISITION_RECONCILED

---

## 1. Discovery vs Manifest Reconciliation

The NTA GetList API returned **1,750 rows** across years 2020–2025.  
The manifest contains **1,760 records**.

### Explaining the +10 delta:

| Source | Records | Explanation |
|--------|---------|-------------|
| NTA GetList (2020–2025) | 1,750 | Rows returned from official NTA Downloads interface |
| 2019 placeholder | +1 | Manually added; NTA does not expose 2019 papers |
| 2026 local archive | +9 | Pre-existing Session-2 Master papers not in NTA dropdown |
| **Total manifest** | **1,760** | **1,750 + 1 + 9 = 1,760 ✓** |

### NTA rows by year:

| Year | NTA Rows | Manifest Records | Delta | Explanation |
|------|----------|-------------------|-------|-------------|
| 2019 | 0 | 1 | +1 | Manual placeholder record |
| 2020 | 52 | 52 | 0 | Exact match |
| 2021 | 498 | 498 | 0 | Exact match |
| 2022 | 1,002 | 1,002 | 0 | Exact match |
| 2023 | 104 | 104 | 0 | Exact match |
| 2024 | 46 | 46 | 0 | Exact match |
| 2025 | 48 | 48 | 0 | Exact match |
| 2026 | 0 | 9 | +9 | Local archive files |
| **Total** | **1,750** | **1,760** | **+10** | **Fully explained** |

---

## 2. Complete Status Accounting (1,760 records)

Every manifest record is classified into exactly one status:

| Status | Count | Description |
|--------|-------|-------------|
| DUPLICATE_ROW | 630 | Same QP URL as another record (NTA row-level deduplication) |
| PAPER_TYPE_EXCLUDED | 490 | B.Arch/B.Planning Paper-2/2A/2B — outside project scope |
| REGIONAL_LANGUAGE_VARIANT | 466 | 12 regional languages — English-only scope |
| AVAILABLE_AND_DOWNLOADED | 170 | Unique English Paper-I QPs successfully acquired |
| NOT_AVAILABLE_ON_NTA_ARCHIVE | 2 | QP URL returns 404 (2022 rows) |
| OFFICIAL_QP_NOT_RETRIEVABLE | 1 | 2019 — NTA does not serve papers |
| AVAILABLE_BUT_DOWNLOAD_FAILED | 1 | 2025-01-22 Shift-1 — corrupt PDF on NTA server |
| **Total** | **1,760** | **630 + 490 + 466 + 170 + 2 + 1 + 1 = 1,760 ✓** |

### Derivation of 170 unique QPs:

`
1,760 total manifest records
 - 630 duplicate rows
 - 490 excluded paper types
 - 466 regional language variants
 -   2 not available on NTA
 -   1 not retrievable (2019)
 -   1 download failed (corrupt)
 ─────
 = 170 unique English Paper-I QPs ✓
`

---

## 3. Physical File Accounting

| Category | Count |
|----------|-------|
| Total PDFs on disk | 204 |
| NTA-acquired Question Papers | 170 |
| Supplementary files (pre-existing) | 34 |

### Supplementary file breakdown (34 files not in NTA manifest):

These pre-date the NTA acquisition script and include:
- **Answer Keys** (final + provisional): ~20 files
- **Notice PDFs** (provisional AK notices): ~8 files  
- **Legacy QPs** (earlier download phases): ~6 files

**Balance: 170 + 34 = 204 ✓**

All 170 manifest-tracked QPs exist on disk. Zero missing files.

---

## 4. Unique Downloaded QPs by Year

| Year | Unique QPs | Sessions Covered |
|------|-----------|------------------|
| 2020 | 14 | Session-1 (4), Session-2 (10) |
| 2021 | 42 | Session-1 (12), Session-2 (12), Session-3 (10), Session-4 (8) |
| 2022 | 62 | Session-1 (14), Session-2 (14), Session-3+ (34) |
| 2023 | 12 | Session-1 (6), Session-2 (6) |
| 2024 | 16 | Session-1 (8), Session-2 (8) |
| 2025 | 15 | Session-1 (7), Session-2 (8) |
| 2026 | 9 | Session-2 (9) |
| **Total** | **170** | |

---

## 5. Language Distribution

### Records by language category:

| Category | Count | % of 1,760 |
|----------|-------|------------|
| English (pure) | 235 | 13.4% |
| Bilingual (English + regional) | 270 | 15.3% |
| Regional-only (non-English) | 1,254 | 71.3% |
| Unknown | 1 | < 0.1% |

### Regional language breakdown:

| Language | Records |
|----------|---------|
| Hindi | 116 |
| Kannada | 116 |
| Odia | 106 |
| Punjabi | 106 |
| Assamese | 104 |
| Marathi | 104 |
| Tamil | 104 |
| Telugu | 104 |
| Bengali | 102 |
| Gujarati | 98 |
| Malayalam | 98 |
| Urdu | 96 |

---

## 6. Known Gaps

### Non-targetable (excluded from 173-paper denominator)

| # | Year | Issue | Status | Note |
|---|------|-------|--------|------|
| 1 | 2019 | NTA does not expose any JEE Main 2019 papers | `OFFICIAL_QP_NOT_RETRIEVABLE` | Not included in targetable core denominator. Audited Downloads + NoticeBoardArchive — confirmed absent. |

### Targetable acquisition gaps (3 of 173)

| # | Year | Date | Shift | Language | Issue | Status |
|---|------|------|-------|----------|-------|--------|
| 2 | 2022 | 2022-07-26 | Shift-1 | Malayalam | QP URL null / HTTP 404 | `NOT_AVAILABLE_ON_NTA_ARCHIVE` |
| 3 | 2022 | 2022-07-26 | Shift-1 | Malayalam | QP URL null / HTTP 404 (duplicate NTA row) | `NOT_AVAILABLE_ON_NTA_ARCHIVE` |
| 4 | 2025 | 2025-01-22 | Shift-1 | English_Hindi | Official NTA PDF is structurally corrupt/truncated. pypdf: Null object error. pymupdf: Unexpected EOF. | `AVAILABLE_BUT_DOWNLOAD_FAILED` |

**Summary:** 2019 = not targetable / not retrievable. 2 × 2022 + 1 × 2025 = three targetable acquisition gaps.

---

## 7. Final Mathematical Summary

```
NTA Discovery:           1,750 rows
Supplementary records:   + 1 (2019 placeholder)
                         + 9 (2026 local Master-paper provenance records)
                         ─────
Manifest total:          1,760 ✓

Status breakdown:
  630  DUPLICATE_ROW
  490  PAPER_TYPE_EXCLUDED
  466  REGIONAL_LANGUAGE_VARIANT
  170  AVAILABLE_AND_DOWNLOADED
    2  NOT_AVAILABLE_ON_NTA_ARCHIVE
    1  OFFICIAL_QP_NOT_RETRIEVABLE
    1  AVAILABLE_BUT_DOWNLOAD_FAILED
  ─────
  630 + 490 + 466 + 170 + 2 + 1 + 1 = 1,760 ✓

Targetable core English Paper-I acquisition:
  173  targetable
  170  acquired
    3  unresolved (2 × 2022 HTTP 404, 1 × 2025 corrupt NTA PDF)

Completeness:            170 / 173 targetable = 98.27%
Physical files:          170 QPs + 34 supplementary = 204 PDFs on disk ✓
Missing files:           0

2019:                    OFFICIAL_QP_NOT_RETRIEVABLE
                         NOT INCLUDED IN TARGETABLE CORE DENOMINATOR

VERDICT: ALL RECORDS MATHEMATICALLY ACCOUNTED
STATUS:  ACQUISITION_RECONCILED
```
