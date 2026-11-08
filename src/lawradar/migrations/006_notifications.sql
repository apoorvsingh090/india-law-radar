-- 006_notifications: outbound webhook attempts for approved reports (M11).
-- Publication remains exclusively a human approval; dispatch is at most
-- once per (report, webhook) thanks to the partial unique index.
CREATE TABLE IF NOT EXISTS notification_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  change_report_id INTEGER REFERENCES change_reports(id) ON DELETE SET NULL,
  webhook TEXT NOT NULL,
  url TEXT NOT NULL,
  status TEXT NOT NULL,
  http_status INTEGER,
  response_snippet TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_notify_report ON notification_attempts(change_report_id);
CREATE INDEX IF NOT EXISTS idx_notify_status ON notification_attempts(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notify_delivery_once
  ON notification_attempts(change_report_id, webhook)
  WHERE status = 'delivered';
