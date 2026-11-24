PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS requests (
 request_id TEXT PRIMARY KEY, criteria_json TEXT NOT NULL, status TEXT NOT NULL,
 selected_pe_id TEXT REFERENCES inventory(pe_id), error TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
 pe_id TEXT PRIMARY KEY, agency TEXT NOT NULL, institution_name TEXT, agency_id TEXT,
 city TEXT, state TEXT, exam_date TEXT, release_date TEXT, rating TEXT, pdf_url TEXT,
 source_url TEXT NOT NULL, snapshot_path TEXT NOT NULL, raw_metadata_json TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, scan_status TEXT NOT NULL DEFAULT 'not_assessed',
 download_status TEXT NOT NULL DEFAULT 'not_downloaded', local_path TEXT, sha256 TEXT, bytes INTEGER
);
CREATE TABLE IF NOT EXISTS candidates (
 request_id TEXT NOT NULL REFERENCES requests(request_id),
 pe_id TEXT NOT NULL REFERENCES inventory(pe_id), matches_criteria INTEGER NOT NULL,
 PRIMARY KEY(request_id,pe_id)
);
CREATE TABLE IF NOT EXISTS download_attempts (
 attempt_id INTEGER PRIMARY KEY, pe_id TEXT NOT NULL REFERENCES inventory(pe_id),
 timestamp TEXT NOT NULL, requested_url TEXT, final_url TEXT, status TEXT NOT NULL,
 http_status INTEGER, local_path TEXT, bytes INTEGER, sha256 TEXT, error TEXT
);
