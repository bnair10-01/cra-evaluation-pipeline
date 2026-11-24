# Edge-case coverage map

One entry for every row of `EDGE_CASES.md`. **Covered** = an automated test exercises the behaviour (file named). **Partial** = some sub-cases tested; the rest are listed.
**Open** = not implemented or not testable here, with the reason. Local results: macOS only. **Windows and Linux are unverified until the CI workflow (`.github/workflows/ci.yml`) has actually run.**
Test files: `A`=test_acquisition, `F`=test_fdic_ffiec, `P`=test_pilot, `W`=test_workflow, `IO`=test_io_provider, `PT`=test_prepare_tables, `TP`=test_tasks_pipeline, `RSE`=test_review_score_export, `PA`=test_portability_acquisition, `BC`=test_batch_cli, `RC`=test_real_corpus, `R`=test_research, `PR`=test_provider.

| Area | Status | Evidence / what is missing |
|---|---|---|
| Configuration | Partial | Duplicate keys, NaN/Infinity rejected for all pipeline JSON (IO). Acquisition manifests and `config/*.json` still use plain `json.loads`: duplicate-key and unknown-option checks are not applied there. |
| Counts and dates | Partial | Zero, negative, reversed range, shortage (PA, W, P). Not tested: leap day, incomplete date, future year. |
| Strings and paths | Partial | Unicode and spaces in paths, leading-zero IDs (IO, PT, PA, RSE). Not tested: apostrophes/"The" names beyond legacy tests, Windows drive/UNC paths (CI only). |
| Named requests | Covered | W, A, F: same-name banks, location present/absent/wrong, name-year-only, fuzzy ranking. |
| Research identity | Partial | `identity_mismatch` flag and leading-zero comparison (RSE); RSSD crosswalk with conflict/unmatched states (RSE). Merged/renamed/successor institutions are only flagged for review, not resolved automatically. |
| Source dates | Covered | `date_differs_from_ffiec`, exam vs period end, prior-date logic (RSE); listing dates never used as research dates (A, F; R). |
| Sampling | Covered | P, W: deterministic, shortage, exclusion, reversed inventory, different seed. Changed-snapshot behaviour: legacy test only (A). |
| Selection exclusions | Partial | Exclusion by canonical examination key (P). Alternate-URL and duplicate-content cases rely on checksum uniqueness (preflight, RC). |
| Reserves | Covered | P: replacement, scan replacement requires confirmed scan; W: resume preserves failed slot. |
| Pagination | Partial | RSSD snapshot rejects incomplete enumeration (RSE). FDIC truncation is not silent (A). OCC/FRB result-cap and changed-header detection: **open**. |
| HTTP | Partial | 403 fails at once; 429/5xx bounded retries (PA). DNS/TLS/timeout retry paths exist but are not unit-tested. |
| Retry-After | Covered | Seconds, HTTP date, negative, invalid, missing, huge (PA). |
| Redirects | Partial | HTTPS-only allowlist incl. look-alike hosts (PA). Redirect loops rely on urllib's limit; credential leakage cannot occur (no credentials are sent). |
| Robots/policies | Partial | Legacy behaviour (HTML robots needs reviewed exception). No new tests; Crawl-delay changes untested. |
| Files | Covered | HTML, truncated, empty rejected; different bytes at same path refused (PA, PT). Oversized (100 MB bound) untested. |
| Storage | Partial | Atomic writes, unique temp names, no partial files (IO, PA). **Open:** disk full, permission denied, symlink/path traversal. |
| Integrity | Covered | Preflight hash/read-only/unique-hash checks (BC, RC); final PDFs unchanged (RC). Manifest tampering: hash mismatch fails preflight. |
| PDF structure | Covered | Encrypted, truncated, HTML, empty fail loudly; page labels; zero pages (PT). |
| Geometry | Partial | Landscape width recorded (PT). Rotation attribute recorded but no rotated fixture; giant dimensions: render bound exists (`render_page_png`), untested. |
| Blank pages | Covered | Confirmed blank vs image-no-text vs sparse (PT); the one real blank page found (RC). |
| OCR | Partial | Classification of image-only, hidden OCR layer, sparse (PT, RC). **Open:** actual OCR accuracy; Tesseract is not installed here, so `ocr_page` has only an error-path test. |
| OCR tools | Covered | Missing executable is an explicit error (PA). Crash/timeout/huge-image paths: open. |
| Table structure | Partial | Dash vs zero, wrapped/stray text rejected, per-page continuation (PT, TP). Areas-down-the-side tables with wrapped labels are read from the cell extraction and checked against the real Hawaii Table O (RC). Merged cells, rotated tables, loan-size tables and rows with missing cells are reported as unread, not read. |
| Table semantics | Partial | Column meanings (count vs dollars vs %) declared per table; demographic base must be a real printed heading (TP). Correctness of the model's column labelling needs human review. |
| Numeric values | Covered | Commas, %, $, parentheses, dash, zero, boundary matching (93 vs 93.3) (PT, TP). |
| Booleans | Covered | Phrase evidence, no printed 1/0 required, bool type rejected (TP). |
| Narrative | Partial | Exact quotes verified on the page (TP). Negation, prior-vs-current, subject/time are prompt rules plus human review; no automatic check. |
| Scope | Partial | Area/product links resolved by name, NULL + flag if unresolved (TP). |
| Model instructions | Covered | Injection text is data only, sits inside `<source_pages>` (TP). |
| Provider setup | Covered | No key, wrong model, 4xx unbilled (IO, BC). |
| Model output | Covered | Refusal, malformed, duplicate keys, trailing text, wrong shape, model mismatch (IO, TP, BC). |
| Context/output | Covered | Truncation splits and is never accepted, sync and batch (TP, BC). |
| Budget | Covered | Boundary sends zero requests, restart persistence, locked cap, task-key attempts, tamper refusal, batch release (IO, BC, PR). Concurrent writers: SQLite `BEGIN IMMEDIATE` used, not stress-tested. |
| Usage | Covered | Overrun recorded and counted, missing usage, raw-write failure after billing, cache-write priced at the dearer tier (IO). |
| Cache | Covered | Page text/hash change invalidates; corrupt entry re-requested; failure markers stop repeat spend (TP, BC). |
| Worker process | Partial | Legacy argument-array worker kept and tested (R). Shell-injection and stderr-secret cases: argument arrays only, not separately tested. |
| Evidence | Covered | Wrong page, quote absent, number not in quote, orphan/cross-document IDs (TP, R). Right quote in the wrong *cell* cannot be fully detected automatically; table rows come from code-read lines, everything else needs review. |
| OCR attestation | Covered | Worker `image_verified` ignored; attestation by name and page only (TP, RSE). |
| Database | Partial | FK enforcement, rollback preserves accepted rows, accept is atomic with backup (R, RSE). Competing writers not stress-tested. |
| Replay | Partial | Cache replay, status skip, accepted/reviewed documents not re-run (TP, BC). Interruption mid-run relies on per-document transactions; no kill-signal test. |
| Reference coding | Covered | Blind attestation required, missing IDs reported, no model output in packets (RSE). |
| Scoring | Covered | Omissions/additions in denominators, zero denominators, missing documents, duplicate contexts (RSE). |
| Adjudication | **Open** | Original predictions and references are hash-locked and the holdout log records every scoring run, but no adjudication workflow (separate corrected records) is implemented. |
| Export | Covered | Draft vs release gates, NULL convention, atomic publication, no leftovers (RSE). |
| Portability | Partial | `CRA_ROOT`, locks, no fcntl, UTF-8 everywhere, CI matrix defined. **Windows/Linux not yet run.** |
