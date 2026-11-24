# Data dictionary

## Storage conventions

- All research fields are nullable. SQL NULL represents missing/unreported information; do not substitute zero, false, or the string "null".
- IDs are stable application-assigned text identifiers. Institution identifiers remain text to preserve leading zeros.
- Dates use ISO `YYYY-MM-DD` only when a complete date is reported. Preserve incomplete dates as printed; do not invent missing components.
- Boolean fields use 1 for true, 0 for false, and NULL for unknown. An unmentioned optional CD test does not imply false.
- Percentages store percentage points: 23.4 means 23.4%, not 0.234. Preserve exact printed formatting in `field_evidence.value_as_printed`.
- Dollar amounts, assets, and LTD measures use text to preserve units, symbols, precision, and reported ranges. No conversion or calculation is required.
- `loan_years`, `years`, `counties`, and `tract_list` retain reported text. `tract_counts_by_income` stores a JSON object with keys `low`, `moderate`, `middle`, `upper`, and `not_available`; unreported values are null. Preserve the source representation in evidence.
- Rating fields preserve reported labels; do not force test ratings into the four overall-rating categories. Validation of overall ratings happens during future data entry/extraction.
- `page` and `pdf_page` are physical PDF page numbers starting at 1. Printed labels, including Roman numerals and appendix labels, belong in `printed_page_label`.
- `exam_type_verbatim`, `data_source_verbatim`, `weight_text`, `label_verbatim`, `benchmark_emphasis_text`, `context_reasons_text`, `hmda_status_text`, `community_contact_text`, `credit_needs_text`, `census_vintage`, and `source_note` retain source wording.
- Table D category text supports the guide's income categories and detailed reported revenue categories. Keep periods separate; do not combine rows merely because the other dimensions match.
- Table E `criterion` identifies the discussed measure; `level` identifies criterion, income-category, or overall assessment. An absent product/area link stays null rather than assigning an inferred context.
- Each populated research value should have one or more evidence records naming its table, primary-key record ID, and field. Assigned IDs do not need documentary evidence. Multiple supporting pages use multiple evidence rows. Evidence coverage is a future application validation rule, not a SQL insert constraint.
- Evidence must support the correct row and column context; a number alone is insufficient for a table cell. Use table text and headers where appropriate.

## Column definitions

The SQL schema specifies allowed category values and relationships. Below are all actual database columns; no placeholder rows are included.

### field_evidence

| Column | SQLite type | Required |
|---|---|---|
| evidence_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| table_name | TEXT | Yes |
| record_id | TEXT | Yes |
| field_name | TEXT | Yes |
| pdf_page | INTEGER | Yes |
| printed_page_label | TEXT | No |
| evidence_verbatim | TEXT | Yes |
| value_as_printed | TEXT | No |

### ltd_peers

| Column | SQLite type | Required |
|---|---|---|
| peer_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| institution_name | TEXT | No |
| location | TEXT | No |
| assets_stated | TEXT | No |
| ltd_ratio_stated | TEXT | No |

### table_a_exam_level

| Column | SQLite type | Required |
|---|---|---|
| pe_id | TEXT | Yes |
| agency | TEXT | No |
| institution_name | TEXT | No |
| agency_id | TEXT | No |
| exam_date | TEXT | No |
| eval_period_start | TEXT | No |
| eval_period_end | TEXT | No |
| exam_type | TEXT | No |
| exam_type_verbatim | TEXT | No |
| rating_overall | TEXT | No |
| rating_lending | TEXT | No |
| rating_cd | TEXT | No |
| rating_investment | TEXT | No |
| rating_service | TEXT | No |
| cd_test_optional_elected | INTEGER | No |
| prior_exam_date | TEXT | No |
| prior_rating | TEXT | No |
| total_assets_stated | TEXT | No |
| as_of_date | TEXT | No |
| ltd_avg | TEXT | No |
| ltd_quarters | TEXT | No |
| ltd_low | TEXT | No |
| ltd_high | TEXT | No |
| hmda_status_text | TEXT | No |
| community_contact_text | TEXT | No |
| credit_needs_text | TEXT | No |

### table_b_products_reviewed

| Column | SQLite type | Required |
|---|---|---|
| product_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| product | TEXT | No |
| is_major_product | INTEGER | No |
| weight_text | TEXT | No |
| data_source | TEXT | No |
| data_source_verbatim | TEXT | No |
| universe_count | INTEGER | No |
| universe_dollars | TEXT | No |
| sample_count | INTEGER | No |
| sample_dollars | TEXT | No |
| loan_years | TEXT | No |
| eval_period_start | TEXT | No |
| eval_period_end | TEXT | No |
| inside_aa_count_pct | NUMERIC | No |
| inside_aa_dollar_pct | NUMERIC | No |

### table_c_assessment_areas

| Column | SQLite type | Required |
|---|---|---|
| aa_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| aa_name | TEXT | No |
| state | TEXT | No |
| msa_or_nonmsa | TEXT | No |
| review_scope | TEXT | No |
| counties | TEXT | No |
| tract_list | TEXT | No |
| tract_counts_by_income | TEXT | No |
| census_vintage | TEXT | No |

### table_d_distribution_measures

| Column | SQLite type | Required |
|---|---|---|
| distribution_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| aa_id | TEXT | No |
| product_id | TEXT | No |
| dimension | TEXT | No |
| category | TEXT | No |
| bank_count | INTEGER | No |
| bank_count_pct | NUMERIC | No |
| bank_dollars | TEXT | No |
| bank_dollar_pct | NUMERIC | No |
| aggregate_pct | NUMERIC | No |
| demographic_pct | NUMERIC | No |
| demographic_base | TEXT | No |
| years | TEXT | No |
| source_note | TEXT | No |
| table_label | TEXT | No |
| page | INTEGER | No |

### table_e_examiner_conclusions

| Column | SQLite type | Required |
|---|---|---|
| conclusion_id | TEXT | Yes |
| pe_id | TEXT | Yes |
| aa_id | TEXT | No |
| product_id | TEXT | No |
| criterion | TEXT | No |
| category | TEXT | No |
| years | TEXT | No |
| label_verbatim | TEXT | No |
| level | TEXT | No |
| benchmark_emphasis_text | TEXT | No |
| context_reasons_text | TEXT | No |

