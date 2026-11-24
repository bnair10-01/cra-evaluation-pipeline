# Pilot acquisition

Use Python 3.10 or later with pdfplumber available (the Codex bundled runtime
includes it). Run from the project root with `PYTHONPATH=src`.

- `python3 -m cra_acquisition.workflow --pilot`: preview four named documents
  plus the seeded draw of 40 from the local FFIEC export.
- `python3 -m cra_acquisition.workflow --count 6 --years 2020 2020 --seed 20261103`:
  preview two per agency, for one year.
- `python3 -m cra_acquisition.workflow --requests config/development_sample.json`:
  preview named evaluations. For custom bank requests use the same JSON format,
  optionally adding `"years": [2010, 2020], "all_matches": true`.
- Add `--output reports/pilot_plan.json` to save a preview as a frozen plan.
  The plan includes the source checksum and ordered reserves.
- `python3 -m cra_acquisition.retrieve reports/pilot_plan.json --limit 8`:
  run or resume up to eight new retrieval attempts. Repeat in bounded batches.
  The progress report is the checkpoint, and the final report is written only
  after all selected files and quota scans are verified. Raw development files
  are reused by checksum; new PDFs are stored read-only in `data/pilot_cache`.
  A final manifest distinguishes selected PDFs from screened reserves.

FDIC dates in this workflow are FFIEC reported dates, linked by certificate
and publication date. OCC/FRB lookup requires matching official ID and date.
Network access errors remain retryable and do not cause silent replacements.

For a supported browser export, pass `--imports FILE`. FILE is a JSON object
keyed by frame PE ID, with a `listing` path to saved official FRB results HTML
and optionally a `pdf` path to that listing's downloaded file. A human
operator must verify that a supplied local file is from the selected exact
link. The listing is parsed and stored as provenance. Do not use this mode
to enter a guessed PDF or an unrelated result page.

For visually confirmed scans pass `--confirmed-scans FILE`. FILE maps
frame PE IDs to `{"sha256": "...", "review_note": "..."}`. The automated scan
hint alone never counts toward the required four. Review near-full-page
images with hidden OCR text as potential scans. Scan screening does not OCR
or populate research tables.

Previews work offline. Live acquisition still depends on readable official
listings and available documents. One- and two-year publication lags are
included in the OCC lookup; files beyond that horizon require review.

## Evidence import for research tables

After freezing a final manifest, run `python3 -m cra_acquisition.research prepare
--final reports/final_RUN.json --pe-id FRAME_ID --pages pages.json` to create
page text, coordinates and table candidates. Optional `--ocr` uses local
Tesseract if available. Prepare a structured proposal manually or with an
extractor. Its top-level keys are `sha256` and `tables`. Include all six
research tables (A–E and LTD peers), with empty lists where applicable. Rows
contain `ids` (primary and foreign IDs) and `fields`. Each populated field
contains `value`, `page`, `quote` and, where applicable, `value_as_printed`,
`printed_page_label`, and a reviewer-supplied `image_verified` for OCR.
Run the same command with `commit --proposal proposal.json` instead of
`prepare`. The commit checks the PDF again and stages all rows and evidence
in one transaction. Use the same OCR option for prepare and commit.

Automated proposal generation and independent reference coding are separate
from this evidence import. A passing structural validation does not establish
that a table cell, scope, or contextual interpretation is correct.

## Independent validation

Use `python3 -m cra_acquisition.score split --input reports/final_RUN.json
--output reports/split_RUN.json` to freeze the 28 calibration / 12 holdout
split. Code holdout references without opening model outputs. Each scoring row
specifies `pe_id`, `table`, `context`, `field`, and `value`; mark reference
identity and numeric fields `critical: true` per the coding guide. Use the
same context key convention in references and predictions (criterion,
assessment area, product, period, and category when applicable). Score with
`python3 -m cra_acquisition.score score --input reports/split_RUN.json
--reference reference.json --predicted predictions.json --output scores.json`.
A missing denominator is reported as null, never as a passing score.

`reports/pilot_plan.json` is a frozen 44-document selection plan, not proof of
44 downloads. `reports/pilot_live_gate.json` records the initial live probes;
the Federal Reserve follow-up is `reports/federal_historical_verified.json`.
Neither smoke-probe PDF nor reserve screening changes membership in the
official sample. The workflow does not automatically present human review as
complete or write model-generated research records without a proposal.

## Handoff export

`python3 -m cra_acquisition.handoff --database data/research.sqlite
--manifest reports/final_RUN.json --review review.json --scores scores.json
--output reports/handoff_RUN` produces CSVs, an independent SQLite copy,
the examiner phrase frequency table, and the inventory and validation
reports. It refuses output if the evaluation set, evidence links, scores, or
mortgage review are incomplete. A reviewer supplies the three indicators for
each evaluation, with boolean values and notes keyed by the identifiers in
`handoff.INDICATORS`, and records any wrong-entity issues and pilot metrics.
The current proposal import expects manual or externally generated proposals;
a model backend and independent human reference records are not bundled.

## Batch proposal worker

`python3 -m cra_acquisition.extract --manifest FINAL --worker WORKER.json
--database STAGING.sqlite --cache CACHE_DIR --report ATTEMPT.json
--pe-id FIRST --pe-id SECOND --limit 2` runs a configured worker. Initialize
the staging database with the research schema first. The worker
configuration contains a `command` argument array, `model`, `version`,
optional `instruction`, and optional `ocr` and `timeout_seconds`.
The worker reads a page-and-table bundle, field definitions, and document
ID as JSON from stdin, and prints the structured proposal JSON to stdout.
The runner validates evidence, commits good proposals transactionally, and
records failures and wall time. It reuses valid cached proposals for the
same input and configuration. It does not include or invoke a provider by
default; independent reviewer labels must never be passed to the worker.


## Extraction pipeline (added 2026-11-22)

See `START_HERE.md` for the `cra` command sequence. Modules: `prepare` (pages), `segment`/`tables`, `tasks` (schemas, merge, Table D reader), `pipeline`/`batch` (calls and cache), `research` (evidence rules), `validate`, `review` (stage/accept/freeze), `packet`/`score`/`handoff` (blind review, scoring, gated export), `rssd`, `estimate`, `memo`.
