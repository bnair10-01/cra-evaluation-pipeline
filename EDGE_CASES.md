# Edge cases and required verification

This is the required regression inventory, not a claim that every case is implemented or tested. No finite list covers all possible failures. Unknown cases must enter an auditable review/failure state, preserve evidence and add a reproducing test when fixed.

## Test classification

- Unit: isolated parsing, matching, schema, budget and score fixtures.
- Integration: real SQLite transactions, files, locks, cache and worker process boundaries.
- Provider mock: injected responses/errors without charges.
- Live bounded: official sources and minimal paid extraction only after preflight and budget reservation.
- Human: blind reference coding and source-image review; never simulated as real approval.
- Platform: actual Windows/Linux/macOS jobs. Passing locally is not platform certification.

## Matrix

| Area | Required cases | Expected result |
|---|---|---|
| Configuration | Missing file, malformed JSON, duplicate keys, unknown options, conflicting config/CLI, wrong types, missing identifiers | Deterministic validation; no silent precedence or guessed values |
| Counts and dates | Zero/negative/noninteger counts, reversed range, leap day, incomplete date, future year, empty eligible pool | Explain exact invalid field or shortage; no hidden relaxation |
| Strings and paths | Unicode, apostrophes, leading/trailing spaces, punctuation, names beginning The, paths with spaces, Windows drive/UNC paths, leading-zero IDs | Preserve originals and document normalization |
| Named requests | Multiple same-name banks, multiple exams, same bank different years, location supplied/absent/wrong, fuzzy-only result, missing agency | Apply agreed filter/fallback only where authorized; record selected identity |
| Research identity | Matching name but different institution, merged/renamed bank, charter conversion, conflicting ID/location, successor institution | Require supported identity; never copy acquisition fallback into research facts |
| Source dates | FFIEC/FDIC release/cover differences, publication lag, product periods, exam start vs evaluation end, partial dates | Preserve source/date meaning; no silent release-date substitution |
| Sampling | Duplicate keys, conflicting duplicates, changed snapshot, reverse order, same/different seed, too few strata, unavailable method, scanned reserve exhaustion | Reproducible frozen run; explicit shortage |
| Selection exclusions | Development IDs with different internal ID, alternate PDF URL, duplicate content, same exam in multiple listings | Exclude canonical examination, not just one internal ID |
| Reserves | Repeated failed reserve, access failure vs unavailable, same-group replacement, scan adjustment, original draw recovery after code defect | Log original/new/reason; preserve quotas; no opportunistic silent resampling |
| Pagination | Zero rows, capped results, next-page loops, changed sort, missing pages, changed headers | Detect incomplete enumeration before claiming coverage |
| HTTP | 401/403, 404/410, 429, 500/502/503, timeout/DNS/TLS, unexpected content type | Correct bounded retry/review; no bypass or false missing-document evidence |
| Retry-After | Seconds/date/missing/invalid/negative/very long value, system clock difference | Safe bounded defer and persisted state |
| Redirects | Relative URL, host change, loop, downgrade to HTTP, credential leakage, unapproved domain | HTTPS host allowlist and applicable robots checks; reject unsafe redirect |
| Robots/policies | Missing/404 robots, HTML in robots, disallow, crawl-delay change, review exception expiration | Explicit review and rate control; HTML is not blanket permission |
| Files | Empty, HTML named PDF, invalid signature, missing EOF, truncated object streams, oversized response, changed bytes at same URL | Preserve/quarantine and error; no accepted overwrite |
| Storage | Disk full, permission failure, symlinks/path traversal, existing filename different hash, incomplete temporary file | Safe project paths and atomic publication |
| Integrity | Hash mismatch, writable original, missing PDF, duplicate bytes, final manifest tampering | Stop/review; keep immutable originals and source history |
| PDF structure | Encrypted, corrupt, unsupported stream, repair needed, missing fonts, page labels/Roman labels, page count zero | Account for every page, preserve original and parser limitations |
| Geometry | Landscape, rotation, crop boxes, giant dimensions, multiple columns, overlapping text | Stable physical page coordinates and bounded rendering |
| Blank pages | Truly blank vs image with no text vs unreadable content | Blank confirmed separately; never treat unreadable as unreported |
| OCR | Image-only, mixed, hidden OCR, partial text, low confidence, skew, noise, wrong language, character substitutions | Quality-driven OCR and review; no automatic trust in text layer |
| OCR tools | Missing executable/language, crash, timeout, huge image, stderr leak | Explicit preflight/failure; no OS-specific hidden fallback |
| Table structure | Multi-page continuation, repeating headers, merged cells, nested groups, wrapped row names, footnotes, rotated appendix | Preserve row/header/context; no silent column shift |
| Table semantics | Count vs dollars, percentages vs totals, aggregate vs demographic, changed denominator/year, missing NA category | Verify complete observation, not number alone |
| Numeric values | Zero/blank/dash, negative, parenthetical negative, comma, scale, decimal precision, rounding, printed errors | Preserve raw units and source; flag inconsistency, no invented arithmetic |
| Booleans | Elected/not elected/not discussed, optional vs required CD, major-product ambiguity | Three-state semantics with phrase evidence; no forced printed 1/0 |
| Narrative | Negation, quoted prior judgments, general background vs current conclusion, repeated phrase, category vs criterion | Exact phrase with subject/time/level; no sentiment scale |
| Scope | Multiple products, periods, states/AAs, full/limited review, overall vs test/state ratings | Context-aware relations and permitted null links |
| Model instructions | Malicious PDF text, supposed system prompt in appendix, commands in retrieved text | Treat all source text as data; no instruction execution |
| Provider setup | Missing/revoked key, unavailable model, changed alias/capability, unsupported schema | Fail before billable work where possible; no silent substitution |
| Model output | Refusal, malformed/trailing JSON, unknown fields, duplicate rows, wrong types, absent keys, NaN/infinity | Retain raw response; reject or bounded repair |
| Context/output | Huge evaluation, oversized section, output max reached, incomplete rows, split table boundary | Split with overlap/context; never accept truncated output |
| Budget | At/below/above cap, restart, concurrent reservation, task-ID changes, alternate ledger, price change, unknown billable timeout | One persistent authoritative cap and attempt accounting; reserve before sending |
| Usage | Missing usage, actual above reservation, cache charges, retry charge, raw write failure after billing | Conservative reconciliation; block rather than hide cost |
| Cache | Changed model/prompt/schema/worker/code/OCR/parser, partial JSON, poisoned cache, stale file, temperature change | Full fingerprint; no reuse without verified inputs and validation |
| Worker process | Wrong command, unavailable dependency, shell injection, timeout, invalid stdout, stderr secrets, nonzero exit | Argument-array invocation, redaction and explicit failure |
| Evidence | Right quote/wrong page, number not in quote, correct quote/wrong cell, orphan row, invalid printed label | Reject unsupported field and track contextual review |
| OCR attestation | Worker claims image_verified, wrong reviewer/hash/page, stale image, incomplete review | External checksum-bound reviewer authority only |
| Database | Duplicate PK, orphan FK, cross-PE child, migration failure, partial commit, competing writers | Foreign keys and transaction rollback; accepted state unchanged |
| Replay | Interrupted download/model/commit, cache corruption, final file modified, replacement duplicated | Idempotent deterministic resume; frozen final membership |
| Reference coding | Predictions visible, missing reviewer, absent holdout IDs, easy subset only, expected rows omitted | Refuse certification; record exposure and incomplete coverage |
| Scoring | Zero denominator, missing critical flags, duplicate context, wrong comparison units, multiple valid passages | Predeclared inventory, correct semantics and transparent counts |
| Adjudication | Reference error, model error, source error, post-holdout tuning | Separate original/reference/corrected records; consumed-holdout disclosure |
| Export | NULL vs empty, Unicode, quoting/newlines, formula-looking strings, partial output, stale inventory, overwrite | Lossless defined convention, atomic versioned release and checksums |
| Portability | Locale, timezone, path case, line endings, executable discovery, lock semantics, PDF rendering differences | Explicit reproducible environment; real three-platform tests |

## Existing test coverage versus missing coverage

26 local tests currently pass: legacy acquisition fixtures, partial date/matching rules, deterministic sampler and shortages, replacement helper, evidence transaction rollback, wrong-context score example, worker cache replay, resume fixture, budget cap and persistent attempt limit. This is NOT comprehensive coverage of this matrix.

Add tests for every untested category before claiming the full gate. Keep a coverage map listing case ID, fixture, test command, platform, observed outcome and unresolved issue. Avoid tests that merely repeat implementation logic; use independently constructed expected examples.

## Final run scenarios

1. Clean environment install and offline manifest/hash audit on each platform.
2. Four development PDFs with every required table family demonstrated where present.
3. Six evaluations for one year; named-only; year-range all-matches; location present/wrong/absent; impossible quota.
4. Same snapshot/seed reversed-input repeat; alternate-seed preview without modifying official pilot.
5. Interrupted download, worker and transaction recovery with no duplicate rows/reserves/charges.
6. Malformed/truncated/wrong-context injection preserves accepted data.
7. Budget below next reservation sends zero provider requests; same task exceeds three attempts fails before request.
8. All 44 complete extraction plus user reference and holdout scoring.
9. Replay unchanged data; stable IDs/hashes/accepted rows/evidence; attempt timestamps may differ.
10. Export refusal when any gate is incomplete, and atomic new version when complete.

Do not declare full pilot success unless independent review, accuracy targets and all release gates actually pass.
