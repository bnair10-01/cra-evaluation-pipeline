# Error log

Each entry: what went wrong, the likely cause, the pipeline change, and the measured effect where one exists. Metrics before and after a prompt change come from the four development documents unless stated; the holdout was never used to tune the pipeline except where noted at the end.

| # | Error | Likely cause | Change | Effect |
|---|---|---|---|---|
| 1 | 44 `criterion` values dropped | merge code applied the numeric-literal rule to text fields | printed-literal rule applies to numbers and dates only | rejected fields 80 -> 10 on the dev set |
| 2 | Table D empty for Wiggins and Park Rapids | `<=` signs stripped when cleaning row labels; Total rows treated as unreadable | keep comparison symbols; skip Total rows | D rows 0 -> 20 / 28 |
| 3 | Same request could be re-billed after a code fix | cache key included merge/validation code | key = the request actually sent; added `--cache-only` replay | fixes since then cost $0 to re-apply |
| 4 | Hawaii wide appendix tables unread | model transcription of 19-column tables is costly and error-prone | model labels columns; code reads cells from pdfplumber's cell view | 54 rows, values verified against the printed header cells |
| 5 | Area names given as whole sentences; sentences as evaluative phrases; blank data sources | prompt too loose | prompts c_areas v2, e_conclusions v2, b_products v2 | aa_name filled 4/6 -> 6/6; data_source 6/11 -> 10/11 |
| 6 | Hawaii small-business sample stored as universe | ambiguous prompt | b_products v3 defines universe vs sample | corrected on re-run |
| 7 | Conclusions under-extracted (Hawaii 4 of about 40) | one large window, low effort, no exhaustiveness instruction | 22k-character windows, e_conclusions v3, conclusions at medium effort | Hawaii 4 -> 43; medium found 130 vs 106 genuine rows on the dev set; self-agreement unchanged (about 91% lenient) |
| 8 | Run aborted on `full-scope` (hyphen) | enumerated values not validated before the database CHECK | allowed-value lists read from the schema and canonicalised; one failing document cannot stop a run | no recurrence |
| 9 | 67 ledger reservations left held | process interrupted while reserving a batch | reservations released on any failure; batch ids persisted to disk; `cra batches` / `cra ledger` | $3.79 still shown held (harmless; release needs `cra batches` check) |
| 10 | Unresolved area links (406) | area names compared after weak normalisation; area-heading pages not sent to the area task | MSA codes/state codes/generic words ignored; heading pages added | 406 -> 115 |
| 11 | `exam_type` NULL although stated | the procedure sentence sat on a page never sent to the exam task | procedure wording pages added | FDIC 53 pp now `large` |
| 12 | Autocoder aborted on a truncated window | no split-on-truncation in that module | split down to single pages; truncation remembered | full run completed, no pages missing |
| 13 | Scorer reported 8% agreement | spelling/format differences counted as disagreement ("Comptroller of the Currency" vs "OCC", `<$1,000,000`, area codes) | identical normalisation of both sides, with tests | Table A coverage 81%, agreement 77% |
| 14 | `review_scope` empty for many areas | scope is printed in a scope section or table row, not on the area page | deterministic fill from a printed phrase next to the area name | precision 36/37 on calibration+dev; areas with scope 71% |
| 15 | Validator flagged "SATISFACTORY" as invalid | case-sensitive comparison | case-insensitive | 2 false flags removed |

## Holdout disclosure
Changes 13-15 were made after the holdout predictions had been compared in aggregate against a model-generated reference. Change 14 alters pipeline output, so the v2 holdout predictions (`reports/holdout_predictions_v2.json`) are **not** a clean out-of-sample test; the original v1 predictions (frozen before any comparison) remain on record. No accuracy claim is made from either.

## Added after the flag review
| # | Error | Likely cause | Change | Effect |
|---|---|---|---|---|
| 16 | `percent_sum` flags doubled on every `cra validate` re-run; stale flags never cleared | validation appended to existing flags | validation flags are replaced on each run (test added) | 246 -> 132 blocking flags |
| 17 | Tables stacked on one page were summed together (sums of 200-400) | grouping ignored table boundaries | consecutive lines form one table; a gap starts the next | 132 -> 110 blocking flags |
| 18 | Open: 109 `percent_sum` flags remain, almost all in areas-down-the-side tables of three OCC large evaluations (and the 112-page FRB), mostly on `aggregate_pct` | not yet diagnosed: either the model mis-labelled columns, or those columns are not a partition of 100 | needs a person to compare 5-10 rows with the PDF; deliberately NOT demoted to non-blocking | open |

## Added 2026-11-22/23 (including my own mistakes)
| # | Error | Likely cause | Change | Effect |
|---|---|---|---|---|
| 19 | Different areas shared one key (Portland OR/ME, Springfield MO/IL); 13 wrong Portland links, 1 wrong Alaska/Idaho link | area matching ignored the state | `areas.py`: state is part of identity, ambiguous names stay unlinked and flagged, spellings of one area are merged | C rows 155 to 141, duplicate pairs 15 to 0 |
| 20 | Earlier report said unresolved links fell 406 to 115 | part of the drop came from the loose matching above | restated in README and MEMORY | unresolved references now 73 |
| 21 | Holdout described as "compared in aggregate" | I printed individual predicted values | holdout recorded as exposed | v1 cannot be called a clean test |
| 22 | Table D agreement reported as 81% | the worst document was left out | restated as 81 of 256 (32%) | |
| 23 | Corpus cost priced 48,688 of 75,028 records | records with no exam type were dropped | memo prices them at the cheapest and dearest type | range, not a point |
| 24 | Conflicting values: the earliest was kept silently | merge rule | critical fields are left blank and flagged `critical_conflict` (4 now) | |
| 25 | A date needed no printed text; area names needed no words on the page | evidence rules too loose | both now rejected without them | 1 area name rejected |
| 26 | Review work lost on every rebuild; gates all-or-nothing; a code fix voided the freeze | decisions lived in the rebuilt database | durable `data/review.sqlite`; two flag levels; freeze covers only model-affecting settings | |
