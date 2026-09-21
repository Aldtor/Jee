# JEE Main bilingual/source-language reconciliation

Generated: 2026-09-21T18:13:47+00:00

The previous Phase 5B `bilingual_papers_total=77` counted both `English_Hindi` and Hindi-only PDFs. This report separates the manifest language labels.

| category | source PDFs | recovered | unresolved |
|---|---:|---:|---:|
| Explicitly bilingual (`English_Hindi`) | 38 | 34 | 4 |
| Hindi-only variant (`Hindi`) | 39 | 37 | 2 |
| English-only (`English`) | 79 | — | — |

The prior Phase 5A count of 13 refers to UNKNOWN format classifications, not bilingual-language PDFs. Those 13 records are therefore not numerically comparable to the current language counts.

Unresolved sources remain explicitly represented in `sources.jsonl`; no OCR status was promoted because a source lacks recoverable question text or is corrupt/partial.
