-- 003_search_index: full-text search over titles + extracted text (M5).
-- search_index holds one row per document version; search_fts mirrors it
-- via triggers. If FTS5 is unavailable the application falls back to LIKE.
CREATE TABLE IF NOT EXISTS search_index (
  doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_id INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  UNIQUE (version_id)
);
CREATE INDEX IF NOT EXISTS idx_search_index_doc ON search_index(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  title, body, doc_id UNINDEXED, version_id UNINDEXED);

CREATE TRIGGER IF NOT EXISTS search_index_ai AFTER INSERT ON search_index
BEGIN
  INSERT INTO search_fts(rowid, title, body, doc_id, version_id)
  VALUES (new.rowid, new.title, new.body, new.doc_id, new.version_id);
END;

CREATE TRIGGER IF NOT EXISTS search_index_ad AFTER DELETE ON search_index
BEGIN
  DELETE FROM search_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS search_index_au AFTER UPDATE ON search_index
BEGIN
  DELETE FROM search_fts WHERE rowid = old.rowid;
  INSERT INTO search_fts(rowid, title, body, doc_id, version_id)
  VALUES (new.rowid, new.title, new.body, new.doc_id, new.version_id);
END;
