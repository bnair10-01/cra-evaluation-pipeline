# Acquisition notes: how the PDFs were collected

> Written during the collection phase. The statements below about research tables being empty or unimplemented are out of date; the project's current state is in `MEMORY.md` and the top-level `README.md`. Acquisition behaviour described here is unchanged.


This project searches official agency listings, retains website metadata, and downloads selected original PDFs. It does not read PDF text, perform OCR, classify scans, or populate research Tables A–E.

## Current development run

- Hawaii National Bank: OCC charter 14911, examination 2020-08-03. Downloaded as `data/raw/OCC/OCC_14911_2020-08-03.pdf`.
- Citizens National Bank of Park Rapids: OCC charter 13692, examination 2023-01-17. Downloaded as `data/raw/OCC/OCC_13692_2023-01-17.pdf`.
- Farmers Savings Bank 2015: unresolved. Multiple institutions share this name, and the FDIC response does not explicitly report examination dates. Review candidates before selection.
- Bank of Wiggins 2024: certificate 8250 found, but the FDIC API explicitly supplies publication date, not examination date. Required filename metadata is unresolved.

See `reports/inventory.html` for a readable inventory and `reports/inventory.json` for full candidate records, links, IDs, provenance, and download status. `reports/summary.json` counts candidate histories by agency and examination year; unknown dates are separate. These are not full-archive coverage counts.

## Running

Requires Python 3.10 or later. No external dependencies or API keys.

From this project directory:

```sh
export PYTHONPATH="$PWD/src"
python3 -m cra_acquisition discover --manifest config/development_sample.json
python3 -m cra_acquisition report --manifest config/development_sample.json
python3 -m cra_acquisition download --manifest config/development_sample.json
python3 -m unittest discover -s tests -v
```

Discovery does not download PDFs. Download operates only on resolved requests in the selected manifest. Report does not access the network.

For ambiguous candidates, explicitly select a candidate belonging to that request:

```sh
python3 -m cra_acquisition select --manifest config/development_sample.json --request-id REQUEST_ID --candidate-id PE_ID
```

Selection does not create missing examination dates. A selected record without a date is still refused by the downloader. Changing manifest criteria requires rediscovery before downloading. Rediscovery recalculates automatic selection; repeat a manual selection afterward when applicable.

## Configuration

`config/development_sample.json` contains the four development requests. The application source contains no bank names, identifiers, target years, or target PDF URLs.

Each request needs a unique `request_id`, `agency`, `institution_name`, and either `exam_year` or `exam_date` (ISO date). Optional `agency_id`, `city`, and `state` narrow matching. Matching is exact except punctuation, case, and a leading "The" in institution names. Name variations are not silently guessed.

For OCC, optional `listing_urls` limits discovery to known official monthly listings. Those two URLs in the development manifest were found from official web listings, not embedded in application code. Without them, the collector follows monthly links from the configured target-year listing. That fallback does not establish complete coverage: examinations may be published in later years. Supply relevant additional-year monthly links explicitly when needed. A missing match remains unresolved.

FDIC searches the institution history through the public endpoint used by its website. All name-matching histories are retained, not only the pilot year. Publication dates and dates embedded in PDF filenames are never treated as examination dates. The response cap (500) causes an error requiring narrower criteria.

Only OCC and FDIC have working discovery adapters. FRB and OTS discovery are explicitly unimplemented, not empty successful searches.

`config/sources.json` holds agency endpoints, request interval, allowed official HTTPS hosts, and the reviewed exception for FDIC's robots endpoint returning its application HTML. Recheck policy notes before expanding hosts or collection volume.

## File organization

- `schemas/research_schema.sql`: existing research definitions, unchanged.
- `data/research.sqlite`: existing empty research database, unchanged.
- `docs/research_data_dictionary.md`: existing research field documentation.
- `schemas/acquisition_schema.sql`: inventory, selection requests, candidate associations, and download-attempt history.
- `data/acquisition.sqlite`: website metadata and file tracking, separate from research values.
- `data/source_snapshots/`: original search responses and robots responses, with provenance sidecars. Policy snapshots have descriptive filenames.
- `data/raw/AGENCY/`: unchanged original PDFs, chmod 0444. Directories remain writable so new downloads can be added.
- `src/cra_acquisition/`: standard-library Python collector and CLI.
- `reports/`: generated HTML and JSON inventories and counts.
- `tests/`: synthetic offline tests; they do not inspect the acquired PDFs.

The original files were moved from the chat's `outputs/cra_tables/` directory. `docs/relocation_checksums.json` verifies identical bytes before removal of the old copies. Research tables remain empty.

## Safety and reproducibility behavior

Every SQLite connection enables foreign keys. Inventory records exist before downloads start. Candidate records retain source URL, retrieval time, snapshot location, and raw website metadata. Repeated discovery uses deterministic IDs to avoid duplicate records. A detected metadata conflict is flagged rather than overwritten; new snapshots preserve changed responses.

Requests use at least two seconds per host, one synchronous client, robots rules where supplied, and longer declared crawl delays. Transient network failures are retried up to three attempts. HTTP 401/403 are not bypassed. Retry-After delays over 60 seconds defer the attempt with a visible error. Do not run concurrent collector processes: the rate limiter is process-local.

The downloader checks only HTTP success, size bound, and the `%PDF-` byte signature. This is not a guarantee of PDF readability; deeper validation is deferred to preserve the no-content-inspection scope. A 100 MB response bound prevents accidentally huge downloads; increase only after reviewing a legitimate case.

Downloads publish atomically without replacing existing files. A rerun verifies checksums before skipping completed files. Different content at an existing target is flagged and preserved. Interrupted files remain outside raw and are downloaded again on retry; HTTP byte-range continuation is not implemented. Each CLI-level attempt is logged; individual HTTP retries within that attempt are not separate database rows.

## Your pending verification

Check the two selected OCC website rows and links against the intended guide examples. Identify the intended Farmers institution (certificate or city/state). Obtain explicit examination dates from an official metadata source for the two FDIC evaluations. Do not use release dates as a substitute or derive dates from filenames. Those records need a reviewed metadata-enrichment step before download; this project does not yet implement automatic FFIEC date enrichment.

No scan count is reported: `scan_status=not_assessed` for every record.

## Requested and random selection update

See `docs/collection_modes.md` for the implemented selection commands and remaining integration work. Requested inputs can omit identifiers and agency when matching against a frozen official metadata inventory. Random selection enforces the agreed 40-document quotas and retains reserves. Fifteen offline tests pass.

This update is partial: direct Federal Reserve and FFIEC metadata access returned HTTP 403, so three-agency automatic retrieval and missing-date enrichment remain unverified. No full pilot was collected. The authorized limited scan classifier and automatic selection-to-download integration remain to be implemented. Existing development acquisition commands are unchanged.

## FDIC filenames using the FFIEC date

FDIC discovery uses the local `data/crarating.txt` export by default. Pass
`--ffiec-file /path/to/crarating.txt` to use another snapshot. The collector
matches the FDIC certificate and publication date to a unique FFIEC row and
uses that row's reported date as `exam_date` for selection and PDF naming.
The original release date stays separate. Inventory metadata records the
FFIEC file checksum, line number, and matching basis. The FFIEC date is a
project naming convention, not a cover-page-verified examination date.

Rerun `discover` before `download` to enrich existing FDIC records. If no
unique FFIEC row matches, the record remains unresolved. Same-name
institutions still require a certificate number or location to disambiguate.

### Selecting by location

Add `"location": "Fostoria, IA"` to a development request to filter exact matches by city and state. The separate `city` and `state` fields still work. Without location, multiple exact matches are resolved by selecting the first match in source order, with the fallback recorded in the report. With location, any remaining ambiguity requires manual selection. A location with no matches never falls back to another city.

## 44-document pilot workflow

See `docs/pilot_workflow.md` for the FFIEC-backed planner, custom acquisition, resumable retrieval, scan confirmation, and research validation commands.
