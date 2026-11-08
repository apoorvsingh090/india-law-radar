-- 004_feedback: user error reports / feedback (M7 public beta).
-- Feedback linked to a report auto-opens a review task (see review queue).
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  change_report_id INTEGER REFERENCES change_reports(id) ON DELETE SET NULL,
  contact TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_feedback_report ON feedback(change_report_id);
