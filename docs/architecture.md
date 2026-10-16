# Architecture (Milestone 1)

```
CLI (argparse) → config.py → logging_config.py → local data dir + sqlite
```

- `src/lawradar/cli.py` — only `init` + `health` in M1. No placeholder commands.
- `src/lawradar/config.py` — YAML file + `LAWRADAR_*` env overrides, safe defaults.
- `src/lawradar/logging_config.py` — stdlib structured logging, stdout or file.
- Package stubs (`models`, `db`, `sources`, `ingestion`, `extraction`,
  `versioning`, `diffing`, `reporting`, `ai`, `review`, `search`, `web`)
  exist as importable packages so M2+ can grow without re-scaffolding.
  Each stub docstring states its milestone — no fake functionality.

Milestone 2 will add: source registry → safe HTTP fetcher → SHA-256 →
dedup → provenance log → extraction. Deterministic diff (M3) must land
before any AI summariser (M4).
