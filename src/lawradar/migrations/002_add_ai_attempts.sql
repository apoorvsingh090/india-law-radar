-- 002_add_ai_attempts: record of AI summarisation attempts per report.
-- A rejected model output is stored here as a failed attempt, never
-- silently repaired into the report.
ALTER TABLE change_reports ADD COLUMN ai_attempts TEXT NOT NULL DEFAULT '[]';
