-- 007_bundles: offline-verifiable evidence export audit trail (M12).
-- One row per exported evidence bundle; paths are unique so a re-export
-- creates a new artifact instead of overwriting the old one. The row
-- survives report deletion (ON DELETE SET NULL) so the export history
-- stays auditable.
CREATE TABLE IF NOT EXISTS evidence_bundles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  change_report_id INTEGER REFERENCES change_reports(id) ON DELETE SET NULL,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  has_document INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (path)
);
CREATE INDEX IF NOT EXISTS idx_bundles_report ON evidence_bundles(change_report_id);
