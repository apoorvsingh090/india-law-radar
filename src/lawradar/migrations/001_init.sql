-- 001_init: full MVP schema (spec section 5). Applied in filename order.
-- change_reports / citations / review_tasks are created now so later
-- milestones only add rows, not tables.

CREATE TABLE IF NOT EXISTS _meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'unknown',
  jurisdiction TEXT NOT NULL DEFAULT 'unknown',
  access_method TEXT NOT NULL DEFAULT 'manual_import',
  terms_review_status TEXT NOT NULL DEFAULT 'not_reviewed',
  poll_interval_minutes INTEGER NOT NULL DEFAULT 1440,
  enabled INTEGER NOT NULL DEFAULT 0,
  last_checked_at TEXT,
  last_success_at TEXT,
  last_error TEXT,
  coverage_notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(id),
  source_document_id TEXT NOT NULL,
  title TEXT NOT NULL,
  document_type TEXT NOT NULL DEFAULT 'unknown',
  issuing_authority TEXT NOT NULL DEFAULT '',
  jurisdiction TEXT NOT NULL DEFAULT 'unknown',
  state_or_ut TEXT NOT NULL DEFAULT '',
  subject_tags TEXT NOT NULL DEFAULT '[]',
  official_url TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'en',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (source_id, source_document_id)
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);

CREATE TABLE IF NOT EXISTS document_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  retrieved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  published_at TEXT,
  effective_from TEXT,
  effective_to TEXT,
  source_modified_at TEXT,
  content_sha256 TEXT NOT NULL,
  raw_storage_path TEXT,
  extracted_text_path TEXT,
  extraction_method TEXT NOT NULL DEFAULT '',
  extraction_status TEXT NOT NULL DEFAULT 'pending',
  language TEXT NOT NULL DEFAULT 'en',
  parser_warnings TEXT NOT NULL DEFAULT '[]',
  is_current_source_version INTEGER NOT NULL DEFAULT 0,
  review_status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE (document_id, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_versions_hash ON document_versions(content_sha256);

CREATE TABLE IF NOT EXISTS change_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  old_version_id INTEGER REFERENCES document_versions(id),
  new_version_id INTEGER NOT NULL REFERENCES document_versions(id),
  change_type TEXT NOT NULL DEFAULT 'unknown',
  diff_text TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  affected_sections TEXT NOT NULL DEFAULT '[]',
  possible_audience TEXT NOT NULL DEFAULT '[]',
  commencement_statement TEXT NOT NULL DEFAULT 'Not established from the extracted evidence',
  claims_json TEXT NOT NULL DEFAULT '[]',
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  reviewer_notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_document ON change_reports(document_id);

CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  change_report_id INTEGER REFERENCES change_reports(id) ON DELETE CASCADE,
  document_version_id INTEGER REFERENCES document_versions(id) ON DELETE CASCADE,
  claim_id TEXT NOT NULL DEFAULT '',
  locator_type TEXT NOT NULL DEFAULT 'text span',
  locator_value TEXT NOT NULL DEFAULT '',
  quoted_text TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  verification_status TEXT NOT NULL DEFAULT 'unverified'
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(id),
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  documents_discovered INTEGER NOT NULL DEFAULT 0,
  documents_downloaded INTEGER NOT NULL DEFAULT 0,
  documents_changed INTEGER NOT NULL DEFAULT 0,
  documents_failed INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON ingestion_runs(source_id);

CREATE TABLE IF NOT EXISTS review_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_version_id INTEGER REFERENCES document_versions(id),
  change_report_id INTEGER REFERENCES change_reports(id),
  reason TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'medium',
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer TEXT NOT NULL DEFAULT '',
  review_notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_tasks(status);
