# JEE Main Complete Archive Verification

**Generated:** 2026-09-21 00:11:03
**Script:** `scripts/verify_jee_main_official_archive.py`

---

## Verification Summary

| Check | Result |
|-------|--------|
| Manifest records | 1760 |
| Downloaded (non-dup) to verify | 170 |
| Passed verification | 170 |
| Errors | 0 |
| Warnings | 0 |
| Physical PDFs | 204 |

## Checks Performed

1. Every manifest local_path exists on disk
2. SHA256 hash matches manifest record
3. PDF signature valid (%PDF header)
4. Not HTML content
5. pypdf parser succeeds
6. Page count > 0
7. No corrupt PDFs classified as valid (1 known corrupt documented)
8. No unexpected duplicate physical files
9. Source URL documented for all recovered assets

## Known Issues

| File | Issue | Status |
|------|-------|--------|
| 2025-01-22 Shift-1 | pypdf: Could not read Null object | OFFICIAL_SERVER_CORRUPT_UNRESOLVED |


## Final Verdict

```
Archive Integrity:    PASS
Manifest Integrity:   PASS
Source Provenance:    PASS
Physical Files:       204 PDFs
Known Corrupt:        1 (2025-01-22 Shift-1)
```
