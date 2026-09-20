# JEE Main Remaining Acquisition Gaps

**Generated:** 2026-09-21 00:05:36
**Recovery Pass:** Complete Official Paper Recovery

---

## A. TARGETABLE OFFICIAL PAPERS STILL MISSING (2)

| # | Year | Date | Shift | Language | Issue | Status |
|---|------|------|-------|----------|-------|--------|
| 1 | 2022 | 2022-07-26 | 1 | Malayalam | NTA row exists but QP URL is null | `NOT_AVAILABLE_ON_NTA_ARCHIVE` |
| 2 | 2022 | 2022-07-26 | 1 | Malayalam | Duplicate NTA row, same null URL | `NOT_AVAILABLE_ON_NTA_ARCHIVE` |

---

## B. OFFICIAL PAPERS NOT PUBLICLY RETRIEVABLE (1)

| Year | Sessions | Issue | Status |
|------|----------|-------|--------|
| 2019 | January + April | No Master QP PDFs ever published. Candidate-login-only recorded responses (decommissioned). | `OFFICIAL_QP_NOT_RETRIEVABLE` |

**Note:** 2019 is NOT included in the 173-paper targetable denominator.

---

## C. OFFICIAL INTERACTIVE-ONLY PAPERS (1)

| Year | Session | Issue | Status |
|------|---------|-------|--------|
| 2026 | Session-1 (Jan) | QPs available only via candidate login during answer key challenge (Feb 4-6, 2026). No public Master QP PDFs. | `OFFICIAL_INTERACTIVE_QP_ONLY` |

**Official Notice:** [Feb 4, 2026 Notice PDF](https://cdnbbsr.s3waas.gov.in/s3f8e59f4b2fe7c5705bf878bbd494ccdf/uploads/2026/02/202602041670681672.pdf)

---

## D. THIRD-PARTY-ONLY DISCOVERY (0)

None. No third-party sources were used.

---

## E. CORRUPT OFFICIAL ASSET (1)

| Year | Date | Shift | Language | URL | Issue | Status |
|------|------|-------|----------|-----|-------|--------|
| 2025 | 2025-01-22 | 1 | English_Hindi | `Paper_20250715180336.pdf` | PDF structurally corrupt on NTA server | `OFFICIAL_SERVER_CORRUPT_UNRESOLVED` |

**Forensic Details:**
- HTTP 200, Content-Length: 5,201,129 bytes
- Valid PDF header (%PDF-1.4), %%EOF present, xref present
- pypdf: "Could not read Null object"
- pymupdf: 0 pages
- 4/4 download attempts return identical SHA256: `7d41e8bd...`
- Range requests supported (HTTP 206)
- **Conclusion:** Internal PDF object corruption, not a network issue

---

## F. 404 OFFICIAL ASSET (0)

None. The two 2022 Malayalam rows had null URLs (never published), not 404 responses.

---

## Summary

| Category | Count |
|----------|-------|
| Targetable still missing | 2 (2022 Malayalam, null URLs) |
| Not publicly retrievable | 1 (2019, never published as Master QP) |
| Interactive-only | 1 (2026 Session-1, candidate login expired) |
| Corrupt official asset | 1 (2025-01-22 Shift-1) |
| Third-party only | 0 |
| 404 official | 0 |
| **Previously missing papers recovered** | **0** |

**No new papers were recovered in this pass.** All gaps are confirmed as genuine
limitations of official NTA publication/infrastructure, not oversights in our search.
