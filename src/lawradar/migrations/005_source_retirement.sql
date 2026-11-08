-- 005_source_retirement: sources removed from the registry stop alerting.
-- History (documents/runs) is preserved; the row is marked retired instead.
ALTER TABLE sources ADD COLUMN retired_at TEXT;
CREATE INDEX IF NOT EXISTS idx_sources_retired ON sources(retired_at);
