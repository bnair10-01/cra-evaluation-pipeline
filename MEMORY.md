# CRA Pilot Project Memory

Updated 2026-11-22. This file is the handoff record for whoever continues the work. `README.md` is for people who use the data; this file is for people who maintain it. It replaces the earlier status and plan files, which were removed because they had become inconsistent. Where this file and old archives (`CRA_*.zip`, `ARCHIVE_CHECKSUMS.json`) disagree, this file wins; those archives pre-date the build and still contain the removed files.

## 1. Where things stand (read first, updated 2026-11-23)

- **Acquisition is complete and unchanged:** 44 verified, read-only PDFs (1,870 pages, 4 confirmed scans), listed in `reports/final_904bed5b30cc793e19d4.json`. Split: 4 development, 28 calibration, 12 holdout (`docs/extraction_handoff/holdout_split.json`).
- **Extraction is staged for all 44** in `data/staging/final.sqlite`, rebuilt from cache at zero cost with the new area logic. Rows: 44 A, 107 B, 141 C, 1,050 D, 2,684 E, 59 peers, 21,387 evidence rows (all linked). Nothing is accepted into `data/research.sqlite`.
- **Export:** `exports/UNVERIFIED-*/` (workbook, CSVs, `evaluations_rssd.csv`, SQLite, PDFs, memo). Labels: UNVERIFIED (default), AUDITED (a person scored 100+ audited values, no error flags), VALIDATED (all gates). It is always written.
- **Flags:** 0 error-level, 262 review-level (201 scanned pages, 29 total mismatches, 27 percent sums, 4 critical conflicts, 1 date). Informational: 493 rejected fields, 352 unread table rows, 1,129 conclusions without an area link.
- **Durable review store:** `data/review.sqlite` holds flag decisions, page attestations, corrections and vision advice, keyed by stable content keys, and survives every rebuild. Values that change show "re-check".
- **Spend:** about $30.1 on Berkley's Anthropic account. Ledger cap is a $150 safety ceiling (`cra ledger --set-cap`).
- **Tests:** 230 pass on macOS. Windows and Linux have never been run. Work is committed locally on branch `cleanup-and-validate` (not pushed).

## 1b. Corrections to earlier statements (the earlier README and memo said otherwise)
- Distinct areas did NOT stay distinct before 2026-11-23: state names were dropped, so Portland OR/ME and the Springfields shared a key. Fixed in `areas.py` (state is identity; an ambiguous name stays unlinked and flagged).
- The holdout is EXPOSED (individual predicted values were printed). v1 is not a clean test.
- Table D agreement is 81 of 256 rows (32%), not 81%; the earlier figure omitted a 2024 FRB evaluation.
- "Unresolved links fell 406 to 115" was partly over-loose matching. The scope rule is 36/37 only when it gave one answer; 41 areas conflicted or had no answer.
- The full-corpus cost priced only 48,688 of 75,028 records; the memo now gives a range.
- Not done: vision check of the 202 scanned pages and the `dc` older-FRB extraction (both paid, need the key), 12 fresh evaluations, blind coding, 300-value audit (the old zip archives and their checksum file were deleted at the user's request). `collect.py`/`pilot.py` were not merged into `workflow.py` because `docs/collection_modes.md` documents them as commands.

## 2. The user's decisions and constraints

- Project folder: the repository root. Keep acquisition and extraction separate; extraction uses the SAME 44 PDFs.
- **Follow the RA guide** (the RA guide (`CRA_PE_Extraction_RA_Guide_Formal.docx`, supplied separately)) for the design; do not redesign it. Do not infer values, calculate figures not printed, repair source inconsistencies, or map examiner language to numbers.
- Model: hosted Anthropic `claude-sonnet-5-5`, Batch API where possible. API key is supplied by the user in their own terminal; never request, print or store it. Paid steps need `--yes-spend`.
- Portable only: no Mac-only services, Apple models, Swift, or user-specific paths in code.
- The user is the only human reviewer. Do not fabricate reviews, attestations, or accuracy. Reviewer actions (`cra review attest`, `submit-reference`, `accept`, `resolve`) are the user's to run.
- **The user asked for the reference coding to be automated (2026-11-22).** `cra autocode` produced a MODEL-GENERATED reference for the 12 holdout documents. It is labelled `reference_kind: model_generated`; scoring against it reports agreement only, cannot pass, and does not open the export's `human_reference` gate. The blind human packet (`reviews/packet_holdout`, blank forms in `reviews/my_coding`) is untouched and still usable.
- FFIEC dates for FDIC file names and sampling (user-authorised); research dates come from the PDF cover. The documented discrepancy is kept.
- Named-bank requests without a location use the first exact match and disclose it (Farmers Savings Bank, Colesburg IA, was selected this way). Random selections never use that fallback.

## 3. Gaps against the RA guide (full table in `README.md` section 9)

Not done or compromised, and why it matters:
- **No hand-coded reference** (~40 evaluations wanted); only the AI reference for 12. No real accuracy figures.
- **Holdout spoiled for validation:** v1 predictions (`reports/holdout_predictions.json`, hash-locked, made under `freeze_v1`) were frozen before any comparison; the scope-fill change (`freeze_v2`, `holdout_predictions_v2.json`) came after an aggregate comparison.
- **Scanned PDFs:** embedded text layer used; no OCR/vision run, no image comparison (Tesseract not installed). No vision fallback for tables in extraction.
- **Count-versus-total check** exists for category tables, not area tables.
- **Three mortgage indicators** are code proposals only (`reports/mortgage_indicators_proposed.json`).
- **RSSD crosswalk** (FDIC BankFind snapshot) matches 41 of 44; it is a separate table, not a Table A column. NIC bulk download returned HTTP 403.
- **Schema addition** (needs the user's sign-off per the guide): `schemas/migrations/002_pipeline.sql` adds bookkeeping tables (doc_status, review_flags, reviewer_attestations, model_requests, rssd_crosswalk). The six research tables and field_evidence are unchanged.
- **Open data problems:** Table D sparse for older FRB and the 112-page FRB evaluation; Table C incomplete for large multi-state evaluations; 1,165 conclusions without an area link; the 109 percent-sum flags are undiagnosed (mostly area-by-category tables in OCC 363/180/40-page evaluations, `aggregate_pct`); one OCC evaluation period ends after its exam date (source inconsistency, kept).
- **Farmers identity:** the guide describes 92 mortgages / 30 reviewed; the selected PDF prints 56 / 27. Ask the user to confirm against original materials.

## 4. What needs a person (next actions)

1. Compare the 202 flagged scanned pages (4 documents) with their page images and run `cra review attest`; spot-check about 5-10 of the percent-sum rows against the PDFs, then resolve or waive the rest with a written note (`cra review resolve`). Do not demote the check to non-blocking.
2. Provide an independent human reference if a genuine accuracy figure is wanted (`reviews/my_coding`, then `cra review submit-reference`). A fresh evaluation set is needed for a clean out-of-sample claim.
3. Attest the four scanned evaluations against page images (`cra review attest`); confirm the mortgage indicators; then `cra review mark-reviewed` / `accept` per document into `data/research.sqlite` (it backs up first).
4. Decide on committing the work, pushing for Windows/Linux CI, and signing off the schema addition.
5. Optional: run `cra batches` with the key set to confirm nothing is in flight, then `cra ledger --release-reserved --reason "..."`.

## 5. How to run

```sh
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q                                       # 230 tests, no network, no key
cra preflight                                             # 44/44 hashes; no key
cra estimate --group all                                  # offline cost estimate
cra extract --group all --run-id X --staging data/staging/X.sqlite --effort-for e=medium --cache-only   # replay from cache, $0
cra validate --run-id X --staging data/staging/X.sqlite   # replaces validation flags; safe to repeat
cra export --database data/staging/X.sqlite --scores reports/holdout_scores_auto_v2.json --indicators reports/mortgage_indicators_proposed.json --output exports
```
Paid order used: development (4) -> calibration (28) -> `cra freeze` -> holdout (12, `--freeze`), always `--batch`, one document at a time in the synchronous path. `cra --help` lists everything (extract, batches, ledger, review, packet, autocode, score, compare, rssd, workbook, memo).

## 6. Canonical paths

- `reports/final_904bed5b30cc793e19d4.json` authoritative 44 documents; `progress_*.json`, `scan_confirmations_*.json` acquisition history; `pilot_plan.json` frozen selection and reserves (about 22 MB, not in git); `page_inventory.json` (1,870 pages classified); `cost_estimate.json`; `pilot_memo.md`; `error_log.md`.
- `reports/freeze_v1.json`, `freeze_v2.json`; `holdout_predictions.json` (+`.lock.json`), `holdout_predictions_v2.json`; `holdout_scores_auto_v1.json`, `_v2.json` (labelled agreement); `mortgage_indicators_proposed.json`.
- `data/raw/` (4 development PDFs) and `data/pilot_cache/` (final PDFs **and unused reserves**: always follow the final manifest, never glob). `data/source_snapshots/` website responses and the RSSD snapshot. `data/crarating.txt` the FFIEC export (83,931 lines; sha256 `59970a2a...0738`; latest date June 2026).
- `data/derived/pages/` prepared page bundles; `data/model/` cache, raw responses, batches, `ledger.sqlite`; `data/staging/` `final.sqlite` (all 44), `staging.sqlite` (dev+calibration runs), `holdout.sqlite`, replicate/experiment databases; `data/drafts/baseline_20261116/` the old partial rule-based draft (NOT research data).
- `reviews/packet_holdout/` blind packet (445 page images, blank forms, instructions; no model output); `reviews/my_coding/` the user's blank forms; `reviews/auto_coding/` the AI reference; `reviews/submissions/voided/` an empty submission, kept for the audit trail.
- `schemas/research_schema.sql` (unchanged), `schemas/migrations/`; `config/` (`sources.json`, `development_sample.json`, `field_inventory.json`, `pricing.json`); `docs/coding_handbook.md`, `research_data_dictionary.md`, `edge_case_coverage.md`, `acquisition_readme.md`.
- Everything under `data/`, `exports/`, `reviews/` and `*.sqlite` is git-ignored; transfer the whole folder, not just the repository.

## 7. How the pipeline works (design to remember)

`prepare` (pdfplumber text/words/tables + pypdfium2 page classes + parser fingerprint) -> `segment`/`tasks.plan` (section windows; conclusions in about 22k-character windows) -> one structured request per target (A exam, B products, C areas, E conclusions, peers, D table layout) as a flat `facts` list `{record, field, value, page, quote, printed}` -> `research.check_field` rules -> merge, deterministic IDs, area/product linking, deterministic `review_scope` fill from printed text -> staging DB -> `validate` flags -> `review` (staged -> reviewed -> accepted).
- **Table D is read by code, not typed by the model:** the model only locates tables and labels columns (category-row text tables, and areas-down-the-side cell tables); code reads the cells and attaches the row text as evidence.
- **Cache key = the request actually sent** (not the merge code), so code fixes replay free with `--cache-only`. Truncated outputs split automatically; refusals and malformed output are errors, never partial results.
- **Ledger:** one locked cap, worst-case reservations before each call, true-cost settlement, 3 attempts per content hash, batch ids persisted so an interrupted run can be collected.
- Evidence rules: typographic normalisation; whole-number matching (93 is not supported by 93.3); allowed-value lists read from the schema (`full-scope` -> `full scope`); a worker's own "image verified" claim is ignored.
- Per-target effort: everything `low`, conclusions `medium` (more genuine conclusions, same self-consistency). Frozen in `freeze_v1/v2.json`.

## 8. Measurements worth remembering

- Cost: final configuration about $0.0062 per page with batch (calibration $8.32 / 1,345 pages; holdout $3.00 / 445 pages). Full-corpus extrapolation about $10,000 batch for 75,028 records (uncertain). Development spend including trials about $30.
- Run-to-run (same model, same documents): Table D numbers identical; conclusions about 91-93% lenient agreement, 76-78% exact phrase; so exact-phrase 95% targets are unrealistic even for the model against itself.
- Agreement with the AI reference (not accuracy): Table A 81% covered / 77% equal; C 63% / 60%; B 38% / 74%; peers 36% / 83%; critical fields by regulator FDIC 53%, FRB 45%, OCC 50% (tables A, B, C, peers); conclusions 67% found leniently; Table D unmatchable by label (reference left identity columns blank), number-only check 81% outside the 112-page FRB document.
- Findings that changed the design: development PDFs contain no FRB, large-bank, scanned or pre-2015 evaluations, so calibration on the other 28 was essential; the three largest evaluations are about 50% of pages (4 over 100 pages: 363, 293, 180, 112); older FRB evaluations rarely print category-row tables.
- Bugs found by measuring (details in `reports/error_log.md`): literal rules applied to text fields; `<=` signs and Total rows in tables; cache key included merge code; area-name matching; truncation not split in the autocoder; validator duplicated and over-summed flags (246 -> 110 blocking); scorer counted spelling differences as disagreement.

## 9. Acquisition facts (kept from the collection phase)

- Frozen run `904bed5b30cc793e19d4`; 13 OCC, 13 FDIC, 14 FRB additional plus 4 development; 4 confirmed scans (Fidelity State Bank 11 pp, Connecticut Bank & Trust 16 pp, American Heritage Bank 15 pp, Arvest 293 pp), all within the additional 40. Five replacements (two parser failures, one unavailable link, two scan-quota replacements).
- Development evaluations: Farmers Savings Bank (FDIC 14807, cover 2015-08-12, filename 2015-12-01); Hawaii National Bank (OCC 14911, 2020-08-03); Citizens National Bank of Park Rapids (OCC 13692, 2023-01-17); Bank of Wiggins (FDIC 8250, cover 2024-07-22, filename 2024-12-01).
- FFIEC export columns (tab separated): institution id, regulator (1 OCC, 2 FRB RSSD, 3 FDIC cert, 4 OTS), date, name, city, state, assets (thousands), method (1 large, 2 small, 7 intermediate small), rating, trailing empty. FFIEC "exam date" equals the FDIC publication date for the records compared; FDIC covers differ. OTS and unsupported methods are excluded.
- Sources: OCC `occ.gov` CRA search and monthly archives (publication lag up to two years); FDIC `crapes.fdic.gov` `POST /api/getSearchResults`, PDFs under `/publish/`; Federal Reserve `federalreserve.gov/apps/CRAPubWeb/CRA/BankRatingResult` (form-encoded, parse the returned DownloadPDF link). Two seconds minimum between requests per host, bounded retries, official HTTPS hosts only; the FDIC robots path returns HTML (reviewed exception in `config/sources.json`). Recheck policies before any new collection.
- An early FRB bug (JSON body instead of form encoding) was fixed; affected selections were retried and the history preserved.

## 10. Don'ts

- Do not re-collect or re-draw the sample, rename files, or change the 44-document manifest.
- Do not change prompts, schemas or settings and then present holdout results as validation.
- Do not accept model output into `data/research.sqlite` without the review steps; do not create attestations, references or scores on the user's behalf; do not mix up `reviews/auto_coding` (AI) with `reviews/my_coding` (human).
- Do not treat the old partial baseline, rehearsal database or `data/staging/*` experiments as research data.
- Do not print or store the API key.
