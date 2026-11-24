PRAGMA foreign_keys = ON;

CREATE TABLE table_a_exam_level (
    pe_id TEXT PRIMARY KEY NOT NULL,
    agency TEXT,
    institution_name TEXT,
    agency_id TEXT,
    exam_date TEXT,
    eval_period_start TEXT,
    eval_period_end TEXT,
    exam_type TEXT CHECK (exam_type IN ('small', 'intermediate small', 'large', 'other')),
    exam_type_verbatim TEXT,
    rating_overall TEXT,
    rating_lending TEXT,
    rating_cd TEXT,
    rating_investment TEXT,
    rating_service TEXT,
    cd_test_optional_elected INTEGER CHECK (cd_test_optional_elected IN (0, 1)),
    prior_exam_date TEXT,
    prior_rating TEXT,
    total_assets_stated TEXT,
    as_of_date TEXT,
    ltd_avg TEXT,
    ltd_quarters TEXT,
    ltd_low TEXT,
    ltd_high TEXT,
    hmda_status_text TEXT,
    community_contact_text TEXT,
    credit_needs_text TEXT
);

CREATE TABLE table_b_products_reviewed (
    product_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    product TEXT CHECK (product IN ('home mortgage', 'small business', 'small farm', 'consumer', 'other')),
    is_major_product INTEGER CHECK (is_major_product IN (0, 1)),
    weight_text TEXT,
    data_source TEXT CHECK (data_source IN ('HMDA', 'CRA-reported data', 'complete bank records', 'examiner sample', 'unclear')),
    data_source_verbatim TEXT,
    universe_count INTEGER,
    universe_dollars TEXT,
    sample_count INTEGER,
    sample_dollars TEXT,
    loan_years TEXT,
    eval_period_start TEXT,
    eval_period_end TEXT,
    inside_aa_count_pct NUMERIC,
    inside_aa_dollar_pct NUMERIC
);

CREATE TABLE table_c_assessment_areas (
    aa_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    aa_name TEXT,
    state TEXT,
    msa_or_nonmsa TEXT,
    review_scope TEXT CHECK (review_scope IN ('full scope', 'limited scope')),
    counties TEXT,
    tract_list TEXT,
    tract_counts_by_income TEXT,
    census_vintage TEXT
);

CREATE TABLE table_d_distribution_measures (
    distribution_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    aa_id TEXT,
    product_id TEXT,
    dimension TEXT CHECK (dimension IN ('borrower income', 'business revenue', 'farm revenue', 'census tract income')),
    category TEXT,
    bank_count INTEGER,
    bank_count_pct NUMERIC,
    bank_dollars TEXT,
    bank_dollar_pct NUMERIC,
    aggregate_pct NUMERIC,
    demographic_pct NUMERIC,
    demographic_base TEXT,
    years TEXT,
    source_note TEXT,
    table_label TEXT,
    page INTEGER CHECK (page >= 1),
    FOREIGN KEY (aa_id, pe_id) REFERENCES table_c_assessment_areas(aa_id, pe_id),
    FOREIGN KEY (product_id, pe_id) REFERENCES table_b_products_reviewed(product_id, pe_id)
);

CREATE TABLE table_e_examiner_conclusions (
    conclusion_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    aa_id TEXT,
    product_id TEXT,
    criterion TEXT,
    category TEXT,
    years TEXT,
    label_verbatim TEXT,
    level TEXT CHECK (level IN ('criterion', 'income category', 'overall assessment')),
    benchmark_emphasis_text TEXT,
    context_reasons_text TEXT,
    FOREIGN KEY (aa_id, pe_id) REFERENCES table_c_assessment_areas(aa_id, pe_id),
    FOREIGN KEY (product_id, pe_id) REFERENCES table_b_products_reviewed(product_id, pe_id)
);

CREATE UNIQUE INDEX product_exam_key ON table_b_products_reviewed(product_id, pe_id);
CREATE UNIQUE INDEX area_exam_key ON table_c_assessment_areas(aa_id, pe_id);

CREATE TABLE ltd_peers (
    peer_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    institution_name TEXT,
    location TEXT,
    assets_stated TEXT,
    ltd_ratio_stated TEXT
);

CREATE TABLE field_evidence (
    evidence_id TEXT PRIMARY KEY NOT NULL,
    pe_id TEXT NOT NULL REFERENCES table_a_exam_level(pe_id),
    table_name TEXT NOT NULL CHECK (table_name IN ('table_a_exam_level', 'table_b_products_reviewed', 'table_c_assessment_areas', 'table_d_distribution_measures', 'table_e_examiner_conclusions', 'ltd_peers')),
    record_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    printed_page_label TEXT,
    evidence_verbatim TEXT NOT NULL,
    value_as_printed TEXT
);

CREATE INDEX evidence_lookup ON field_evidence(table_name, record_id, field_name);
