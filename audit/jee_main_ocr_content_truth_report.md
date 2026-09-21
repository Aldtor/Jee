# JEE Main OCR content truth report

Generated: 2026-09-21T17:21:58+00:00

Final status: `OCR_CONTENT_REVIEW_REQUIRED`

## Source and content metrics

| metric | value |
|---|---:|
| papers_processed | 156 |
| manifest_rows_selected | 170 |
| duplicate_manifest_rows_collapsed | 14 |
| papers_successful | 152 |
| papers_corrupt | 3 |
| papers_partial | 1 |
| questions_structural | 12792 |
| questions_with_real_text | 11087 |
| questions_with_options | 7120 |
| questions_with_images | 11199 |
| questions_ocr_verified | 3899 |
| questions_needs_review | 8787 |
| bilingual_papers_total | 77 |
| bilingual_papers_recovered | 71 |
| bilingual_papers_unresolved | 6 |
| questions_recovered_from_bilingual_papers | 6232 |
| question_crops | 11271 |
| option_crops | 46509 |
| diagram_crops | 17230 |
| placeholder_questions | 0 |
| placeholder_options | 0 |
| critical_ocr_errors | 0 |
| ocr_errors | 2 |

## Database validation

| check | value |
|---|---:|
| sources | 156 |
| questions | 12688 |
| question_occurrences | 12792 |
| options | 53441 |
| answers | 5624 |
| images | 75010 |
| foreign_key_errors | 0 |
| orphan_questions | 0 |
| orphan_options | 0 |
| orphan_answers | 0 |
| orphan_images | 0 |
| invalid_source_references | 0 |
| unique_occurrence_ids | 1 |
| missing_source_pages | 0 |

## Limitations

OCR is retained as raw evidence. Items marked `OCR_REVIEW_REQUIRED` or `CONTENT_PARTIALLY_VERIFIED` remain in the production data with source-page and image provenance. Corrupt and partial official PDFs are explicitly documented and are not replaced.
