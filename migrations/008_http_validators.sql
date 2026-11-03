-- 008_http_validators: conditional-request support for http_poll sources (M13).
-- Validators are per document (the polled URL is the document identity),
-- cached between sweeps so the fetcher can ask the official server with
-- If-None-Match / If-Modified-Since and skip re-downloading unchanged
-- bytes. http_validated_at records the last time the URL was validated
-- (including a 304 answer), so "no change" is visible evidence.
ALTER TABLE documents
  ADD COLUMN http_etag TEXT NOT NULL DEFAULT '';
ALTER TABLE documents
  ADD COLUMN http_last_modified TEXT NOT NULL DEFAULT '';
ALTER TABLE documents
  ADD COLUMN http_validated_at TEXT NOT NULL DEFAULT '';
