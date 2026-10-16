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
- M3 adds deterministic diff + version comparison on top of these versions.
