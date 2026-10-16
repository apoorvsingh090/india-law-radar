# Architecture (Milestone 2)

```
CLI (argparse) → config.py → logging_config.py → local data dir + sqlite
                    ├→ sources/registry.py → DB sources table (sync on every run)
                    ├→ ingestion/pipeline.py → db/store.py → versions + runs
                    │     ├→ ingestion/fetcher.py (allowlist, throttle, cap)
                    │     ├→ ingestion/hashing.py (SHA-256, normalise)
                    │     └→ extraction/text.py (HTML / text / text-PDF)
                    └→ sources/{fixture,manual}.py (no network)
```

- `sources list` syncs the YAML registry into the DB before displaying.
- Every `ingest` opens a run row, syncs the registry, ingests, then records
  success/failure — failures never mark the source successfully checked.
- Raw bytes stored at `data/raw/<sha256>` unless the source policy is
  `restricted`; extracted text always at `data/text/<sha256>.txt`.
- M3 adds: `diffing/compare.py` (raw + normalised diff, section mapping,
  `text_modified`/`possible_amendment`/`corrigendum`/`unknown` labels) →
  `reporting/generate.py` builds a schema-validated draft (spec §8) →
  persisted to `change_reports` + `citations`. Ingest auto-generates the
  draft; `reports generate` backfills. Deterministic diff always lands
  before any AI summariser (M4).
- M4 adds: `review/queue.py` (auto-queue uncertain reports, approve-gated
  `published_at`, notes-required rejections, append-only `review_tasks`
  audit trail) → `reporting/verify.py` (machine citation check, never a
  human sign-off) → `ai/` (`HeuristicSummariser` default,
  `CommandSummariser` only with `ai.enabled` + `ai.command`, output
  validated, failures stored in `ai_attempts`).
- M5 adds: `search/fts.py` (FTS5 `search_fts` mirrored from `search_index`
  via triggers, LIKE fallback, literalised MATCH input) indexed by the
  pipeline per version → `web/server.py` (stdlib `ThreadingHTTPServer`,
  loopback default, token-gated POSTs, no tracebacks to clients) →
  `web/pages.py` (escaped templates for dashboard, feed, detail,
  documents, search, sources, review, coverage) + JSON API
  (`/api/*`, `/health`).   `lawradar serve` refuses non-loopback binds
  without `--token`.
- M6 adds: `sources/legislative.py` (same-host listing parser for
  operator-saved pages) + `sources/egazette.py` (URL builders/validator,
  no live calls) → `evaluation/runner.py` (7-case bounded set, `lawradar
  eval`) → `docs/coverage.md` (per-source live findings) +
  `docs/runbook.md` (failure table, reprocessing recipes).
