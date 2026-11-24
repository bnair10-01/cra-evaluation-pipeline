# CRA pilot memorandum (generated 2026-11-22 23:50 UTC)

Status: generated from measured files only. Sections say "not measured" when no data exists.

## Documents and pages

- 44 evaluations, 1870 physical pages; scanned evaluations: 4.
- Page classes: blank=1, ocr_layer=335, text=1534.
- Pages needing review (image-backed, sparse, or flagged text): 367.
- Longest evaluations: 363 pp (OCC large), 293 pp (FRB large), 180 pp (OCC large), 112 pp (FRB intermediate small), 98 pp (FDIC large).

## Cost

- Offline estimate (price version 2026-11-22): expected $27.73, worst case $56.67 for all documents. Expected output assumes ~35% of each call's max_tokens (including thinking). Worst case reserves 100%. Input uses a conservative 2.5 bytes/token bound; live calls use count_tokens. Batch API would halve both.
- Measured ledger: spent $30.0756, held $3.7869, remaining $116.1374 of $150.00; overruns 0, ambiguous 0.

## Extraction

- staged: 228

### Open review flags by kind

- field_rejected: 2408
- table_row_unread: 1907
- unresolved_reference: 1220
- unlinked_context: 1129
- image_review_required: 402
- column_label_mismatch: 224
- conflict: 189
- column_skipped: 170
- incomplete_distribution: 88
- total_mismatch: 58
- duplicate_row: 46
- layout_rejected: 38
- table_family_empty: 36
- conclusion_without_phrase: 30
- percent_sum: 27
- date_differs_from_ffiec: 16
- critical_conflict: 4
- area_heading_without_row: 3
- date_inconsistent: 1

Requests logged: 3919 (cache hits 3287), cost $17.9518, request seconds 508.

## Pilot inventory (the guide asks for counts by agency and year, scans, and long evaluations)

| Period | FDIC | FRB | OCC | Total |
|---|---|---|---|---|
| 1997-2004 | 3 | 2 | 3 | 8 |
| 2005-2009 | 2 | 3 | 3 | 8 |
| 2010-2014 | 3 | 3 | 2 | 8 |
| 2015-2019 | 3 | 3 | 3 | 9 |
| 2020+ | 4 | 3 | 4 | 11 |

- Scanned (image-only) evaluations: 4 of 44, all with an embedded OCR text layer, so no OCR was needed.
- Exam types: intermediate small 14, large 10, small 20.
- Unusually long evaluations (100+ pages): 4: 363 pp (OCC large), 293 pp (FRB large), 180 pp (OCC large), 112 pp (FRB intermediate small). These 4 documents are 948 of 1870 pages (50%) and were processed in section windows, never as one request.

## Cost and time estimate for the full corpus

- Final-configuration cost with the Batch API was measured on the 28 calibration documents: $8.32 for 1,345 pages = $0.0062 per page (holdout: $3.00 for 445 pages = $0.0067 per page).
- Pilot average length: 42.5 pages per evaluation, so about $0.27 per evaluation with batch.
- The FFIEC export lists 75,028 examination records from OCC/FRB/FDIC; 26,340 of them have no exam type. Priced by exam type (small: 33,031 evaluations x 14 pages; intermediate small: 8,152 evaluations x 28 pages; large: 7,505 evaluations x 120 pages), the typed records alone cost about $10,143 with batch. Pricing the untyped records at the cheapest and the most expensive type's average length gives a total of **$12,461 to $30,372 with batch** (about double synchronously). **This is an extrapolation from 44 documents**, not a measurement: it assumes the pilot's page counts per type hold, ignores the extra cost of very long evaluations, and excludes retries and re-extraction.
- Time: local page preparation took about 3 minutes for all 44 documents. Model time is dominated by Batch API turnaround, which was not timed; plan for hours per few hundred requests, and rate limits would govern a corpus-scale run.
- Human review time recorded so far: 0 hours. No human reference was coded; see Validation.

## Validation (against a MODEL-GENERATED reference; agreement, not accuracy)

The reference was transcribed by a model from page images with a separate prompt, at the project owner's request. No human reference exists. These figures show where two readings agree; they cannot establish correctness, and the export gate for a human reference remains unmet.

| Table | Reference rows | Pipeline has them | Same value when both present |
|---|---|---|---|
| table_d_distribution_measures | 1804 | not matchable by label* | see note |
| table_e_examiner_conclusions | 335 | 20% | 74% |
| table_a_exam_level | 151 | 81% | 77% |
| table_b_products_reviewed | 91 | 38% | 74% |
| table_c_assessment_areas | 161 | 63% | 60% |
| ltd_peers | 50 | 36% | 83% |

*Table D: the reference left the identity columns (dimension, product) blank in most rows, so rows cannot be keyed. A label-free check (does each reference row's set of printed numbers appear as a row in the pipeline output?) found 81 of 256 rows (32%) across all documents; outside the one 112-page FRB evaluation (a 2024 document, so not simply an old-format problem) it found 59 of 73 (81%). The earlier 81% headline left that document out.

- Conclusions: the pipeline found 67% of the reference's 96 judgments (same page, overlapping phrase; 36% with the exact phrase). It produced 560 judgments to the reference's 96, so precision cannot be judged from this reference.
- Critical-field agreement by agency, over the tables that can be matched (A, B, C, peers; n in brackets): FDIC 53% [121], FRB 45% [62], OCC 50% [48]
- By exam type: intermediate small 57% [65], large 56% [78], small 40% [88]
- By scan status: scanned 21% [14], text_based 52% [217]

## Extraction failures and hardest formats

- Very dense distribution tables (appendix tables with income categories across the page) exceed one output window; they are split automatically. Table D rows are read by code, not typed by the model.
- Rotated column headings (for example Park Rapids' appendix) leave only scattered letters in the text layer; `demographic_base` is NULL there and flagged.
- Older FRB evaluations (1997-2010) mostly describe results in sentences and tract lists, not category-row tables, so Table D is sparse for them.
- Large multi-state evaluations (KeyBank 363 pp, Arvest 293 pp, Simmons 180 pp) have dozens of assessment areas; Table C coverage there is incomplete and many conclusions cannot be linked to an area (flagged `unresolved_reference` / `unlinked_context`).
- Four evaluations are scans with an embedded OCR text layer; their quotes still need a person to compare them with the page images (`cra review attest`).


## Schema changes needing consultation

`schemas/migrations/002_pipeline.sql` adds metadata tables (doc_status, review_flags, reviewer_attestations, model_requests, rssd_crosswalk). The six research tables and field_evidence are unchanged.

## Not yet established

Independent reference accuracy, holdout results and full-corpus cost are measured only after the paid and blind-review stages; none is claimed here.
