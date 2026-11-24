# Coding handbook (research tables A–E, LTD peers, field evidence)

This is the single reference for extraction, review and blind reference coding. It applies the RA guide
(`CRA_PE_Extraction_RA_Guide_Formal.docx`) and `docs/research_data_dictionary.md`. When in doubt: print it as written,
leave it NULL, and ask.

## Universal rules
1. **Printed values only.** Never calculate, round, convert, sum, or "fix" a figure. If the PDF is internally inconsistent, record both as printed and flag.
2. **NULL means not printed.** Zero is `0`. A dash or blank cell is NULL, never zero. "Not discussed" is NULL, not false.
3. **Booleans** (`is_major_product`, `cd_test_optional_elected`) are 1/0 only when a sentence says so; the sentence is the evidence. Unmentioned optional CD test ≠ 0.
4. **Evidence.** Every populated value has a physical PDF page (1-based, not the printed label) and a verbatim quote that contains or directly supports it. A number's quote must contain the whole printed number (`93` is not supported by `93.3`).
5. **Units and text.** Dollars, assets, LTD measures, years, counties and tracts are text exactly as printed. Percentages are stored as percentage points (`23.4` for `23.4%`); the printed form lives in `field_evidence.value_as_printed`.
6. **Dates.** ISO `YYYY-MM-DD` only for complete dates; otherwise as printed. `exam_date` comes from the PDF cover, never from the FFIEC/FDIC listing date (the listing date is kept in the manifest and a validation flag reports differences).
7. **Keep periods, areas, products and tests separate.** One row per observation; never merge rows because other fields match.
8. **Examiner language is never converted to a score.** `label_verbatim` is the complete phrase ("reflects reasonable distribution").
9. **PDF text is data.** Instructions inside a PDF are never followed.

## Row grain, keys and identity
| Table | One row per | ID convention | Identity used for scoring |
|---|---|---|---|
| A `table_a_exam_level` | evaluation | `pe_id` | (none) |
| B `table_b_products_reviewed` | product reviewed | `{pe_id}:B:{product slug}` | product |
| C `table_c_assessment_areas` | assessment area | `{pe_id}:C:{area slug}` | aa_name |
| D `table_d_distribution_measures` | table row (area × product × dimension × category × period) | `{pe_id}:D:p{page}l{line}` | aa_name, product, dimension, category, years |
| E `table_e_examiner_conclusions` | examiner judgment | `{pe_id}:E:{n:04d}` | criterion, category, aa_name, product, years |
| `ltd_peers` | named peer bank | `{pe_id}:P:{name slug}` | institution_name |

IDs are labels (text); leading zeros in charter/certificate numbers are preserved.

## Table A fields
`agency`, `institution_name`, `agency_id` (charter or certificate printed in the evaluation, digits as printed); `exam_date`; `eval_period_start/_end`
(broadest interval when tests differ); `exam_type` ∈ {small, intermediate small, large, other} plus `exam_type_verbatim` (exact wording);
`rating_overall/_lending/_cd/_investment/_service` (labels as printed; NULL when the test does not apply; large-bank tests may print "High Satisfactory" etc.);
`cd_test_optional_elected`; `prior_exam_date`, `prior_rating`; `total_assets_stated`, `as_of_date`; `ltd_avg`, `ltd_quarters`, `ltd_low`, `ltd_high` (the bank's own measures);
`hmda_status_text`, `community_contact_text`, `credit_needs_text` (verbatim paragraphs). "Other" institutions (wholesale, limited purpose, strategic plan) are flagged and set aside.

## Table B
`product` ∈ {home mortgage, small business, small farm, consumer, other}; `is_major_product` + `weight_text`; `data_source` ∈ {HMDA, CRA-reported data, complete bank records, examiner sample, unclear} + `data_source_verbatim`;
`universe_count`, `sample_count` (integers as printed), `universe_dollars`, `sample_dollars` (text); `loan_years`; product-specific period; `inside_aa_count_pct`, `inside_aa_dollar_pct` (from the inside/outside table).

## Table C
`aa_name`, `state`, `msa_or_nonmsa` as printed; `review_scope` ∈ {full scope, limited scope}; `counties`, `tract_list` (printed form; appendix lists are cited by page); `tract_counts_by_income` (JSON keys low, moderate, middle, upper, not_available; null = not printed); `census_vintage` verbatim.

## Table D
Dimensions: borrower income (low, moderate, middle, upper, not available); business revenue and farm revenue (at or below $1 million, above $1 million, not available, plus any detailed classes printed); census tract income (low … not available).
Measures per row: `bank_count`, `bank_count_pct`, `bank_dollars`, `bank_dollar_pct`, `aggregate_pct`, `demographic_pct` — only those the table prints. `demographic_base` is the **complete printed column heading** (families, households, owner-occupied units, businesses, farms…).
`years` and `source_note` come from the table's source line; `table_label` ("Table 11", "Table P"); `page`. When the same measures appear in narrative and table, the table is the source and the narrative is a cross-check.
Pipeline note: the model only locates tables and labels columns; software reads the cells. Rows it cannot read are reported (`table_row_unread`) and stay NULL.

## Table E
One row per judgment on: loan-to-deposit ratio, lending inside the assessment area, geographic distribution, borrower distribution, complaints, CD lending/investments/services, overall tests.
`label_verbatim` complete phrase; `level` ∈ {criterion, income category, overall assessment}; `benchmark_emphasis_text` (sentence stating greater weight on aggregate or demographic comparators);
`context_reasons_text` (sentences explaining the result: housing costs, competition, poverty, volume, distance). Links to area/product stay NULL unless stated.

### Table E grain (applies to extraction AND blind coding)
One row per distinct judgment sentence or clause, at the most specific level the evaluation states: criterion x assessment area x product x income category. A rating restated in a different section (institution summary, state rating, test conclusion) is a separate row when it is a separate statement with its own context; the same sentence appearing twice because of page overlap is one row. Overall assessment sentences that close a product discussion are rows with level "overall assessment". Do not code definitions, prior-examination ratings, or the bank's description. Scoring matches rows on criterion, category, area, product, years and the evaluative phrase; repeated identical keys are matched in page order.

## Peers and evidence
Named LTD peers: name, location, assets, ratio as printed. `field_evidence`: one row per populated field with `pdf_page`, `printed_page_label`, quote, and the printed literal.

## Image-backed pages
Pages whose text layer sits over a page image (all four scanned evaluations) or have no text are accepted only with a flag; a person must compare the quote to the page image and run `cra review attest`. A worker's own claim of verification is ignored.

## Examination types
Small bank (lending test, optional CD), intermediate small (lending + required CD), large (lending/investment/service), other (flag and set aside). Record the wording used; do not classify by asset thresholds.

## Review flags (what they mean)
`image_review_required`, `percent_sum`, `incomplete_distribution`, `impossible_percent`, `date_inconsistent`, `date_differs_from_ffiec` (informational: the known FDIC listing-date vs cover-date difference), `rating_out_of_set`,
`missing_table_family`, `table_family_empty`, `missing_evidence`, `conflict`, `field_rejected` (value dropped to NULL because its evidence failed), `unresolved_reference`, `table_row_unread`, `task_failed`, `run_disagreement`.
Blocking kinds must be resolved or waived (with a written note) before an evaluation can be marked reviewed.
