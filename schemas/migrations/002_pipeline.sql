-- Additive migration: pipeline metadata. Existing research tables and columns are unchanged.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_status (
    run_id TEXT NOT NULL,
    pe_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('unprocessed','prepared','extracting','staged','incomplete','failed','unreadable','reviewed','accepted')),
    detail TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, pe_id)
);

CREATE TABLE IF NOT EXISTS review_flags (
    flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pe_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    table_name TEXT,
    record_id TEXT,
    field_name TEXT,
    pdf_page INTEGER,
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','waived')),
    resolution TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS flag_lookup ON review_flags(run_id, pe_id, status);

CREATE TABLE IF NOT EXISTS reviewer_attestations (
    attestation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pe_id TEXT NOT NULL,
    pdf_sha256 TEXT NOT NULL,
    pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    note TEXT,
    UNIQUE (pe_id, pdf_sha256, pdf_page)
);

CREATE TABLE IF NOT EXISTS model_requests (
    request_row INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pe_id TEXT NOT NULL,
    target TEXT NOT NULL,
    window TEXT NOT NULL,
    task_key TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    effort TEXT,
    max_tokens INTEGER,
    status TEXT NOT NULL,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    usage_json TEXT,
    api_request_id TEXT,
    raw_path TEXT,
    error TEXT,
    seconds REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rssd_crosswalk (
    agency TEXT NOT NULL,
    agency_id TEXT NOT NULL,
    rssd_id TEXT,
    fdic_cert TEXT,
    occ_charter TEXT,
    institution_name TEXT,
    active INTEGER,
    source TEXT NOT NULL,
    source_sha256 TEXT,
    status TEXT NOT NULL CHECK (status IN ('matched','unmatched','conflict')),
    PRIMARY KEY (agency, agency_id)
);
