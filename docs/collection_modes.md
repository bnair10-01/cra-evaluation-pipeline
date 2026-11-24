# Requested and random collection modes

## Implementation status

Selection logic is implemented and tested. Fully automatic three-agency retrieval is NOT complete: direct Federal Reserve search and FFIEC ZIP requests returned HTTP 403 on 2026-11-02. These restrictions were not bypassed. No full pilot has been drawn or downloaded. No scan-classification engine has been implemented yet. Existing development PDFs and research schema are unchanged.

## Inputs and commands

From project root, set `PYTHONPATH=src` for each invocation.

Requested records from an official metadata inventory:

```sh
PYTHONPATH=src python3 -m cra_acquisition.collect --frame data/official_inventory.json --requests config/development_sample.json
```

No requested records means a random 40:

```sh
PYTHONPATH=src python3 -m cra_acquisition.collect --frame data/official_inventory.json
```

Four requested records plus an additional random 40:

```sh
PYTHONPATH=src python3 -m cra_acquisition.collect --frame data/official_inventory.json --requests config/development_sample.json --additional-random
```

`data/official_inventory.json` must be a real, frozen official-metadata inventory, not fabricated example records. This file is not yet available. Its JSON array entries require unique `pe_id`, `agency` (OCC/FDIC/FRB), `institution_name`, `exam_date` (ISO), and `exam_type` (small/intermediate small/large). Retain source URL and provenance on every record. Institution identifiers and PDF links may be missing at selection time. Missing examination dates cannot enter period strata until resolved.

Requested inputs need institution_name and exam_year (or year), with optional agency, agency_id, city, state, and exam_date. `year_basis: release` explicitly selects publication-year matching. Default is examination year. Similar names are ranked, not silently selected. Multiple exact-name matches remain unresolved.

`collect` writes `reports/collection_selection.json`. It performs selection only; it does not currently bridge the results into the downloader automatically. The existing acquisition CLI remains available for OCC/FDIC discovery and resolved downloads.

For immutable frame hashing and a download-request manifest, the standalone sampler is:

```sh
PYTHONPATH=src python3 -m cra_acquisition.pilot --frame data/official_inventory.json --seed 20261102
```

An optional `--exclude` points to a JSON list of development pe_ids. Records are sorted before seeded draws. Snapshot hash, seed, exclusions, selected records, reserve order, and scan-completion flag are retained. Existing same-run reports are preserved.

## Selection defaults

Exactly 40 additional evaluations: OCC 13, FDIC 13, FRB 14. Five periods each contribute 8: 1997–2004, 2005–2009, 2010–2014, 2015–2019, and 2020–2026. Each agency must include at least three examples of each examination type. Impossible quotas raise an explicit error rather than being relaxed. The present cutoff is 2026; update the sampling configuration/code deliberately for future years.

The `replace` helper requires the same agency, period, and examination type; scan-quota replacements additionally require confirmed `scan_status=scanned`. It returns a candidate and never silently mutates the selection. Persisting replacement decisions and classifying scans remain unfinished. Four confirmed scans are required before declaring the sample complete. Unknown status is not treated as text or as scanned.

## Remaining work

1. Obtain official FFIEC metadata through permitted access or an official export; implement provenance-preserving date enrichment.
2. Implement and verify Federal Reserve search and document retrieval when permitted access is available.
3. Improve OCC listing discovery across publication years and remove dependency on supplied development monthly links only after live replacement tests pass.
4. Connect resolved collection selections to acquisition/download records and retain replacement decisions in the database.
5. Add the authorized limited text/image scan classifier and manual confirmation queue; no OCR or research-field extraction.
6. Verify older and recent retrieval for all agencies, then draw and collect the 44-document pilot.

Existing OCC listing URLs remain in the development manifest until broader discovery is verified; moving them out of code is not equivalent to automatic search. These limitations must not be presented as completed acquisition functionality.
