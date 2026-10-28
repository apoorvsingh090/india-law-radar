# Deployment (public beta, M10)

The app stays usable locally with no paid service. Anything beyond
loopback needs the guards below — there is no multi-user auth model.

## Option A — local loopback (default, safest)

```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install .
lawradar init
lawradar serve            # http://127.0.0.1:8080
```

Review POSTs are open on loopback by design (single operator machine):
no token is needed, but every POST still requires a loopback `Host` and a
same-origin `Origin`/`Referer` (or a non-browser client with neither), so
a web page cannot drive-by publish a report. `/feedback` is public but
uses the same origin checks and per-IP rate limit.

## Option B — LAN / small team (token required)

```powershell
$env:LAWRADAR_POST_LIMIT_PER_MINUTE = "30"
lawradar serve --host 0.0.0.0 --port 8080 --token "<long-random-secret>"
```

`serve` refuses non-loopback binds without `--token`. Share the token
out of band. Review POSTs require it as a form field; `/feedback` remains
public but is same-origin checked. Rates are limited per client IP
(`post_limit_per_minute`, default 30).

## Option C — always-on host (experimental)

Any Python host works (buildpack-style: `pip install .`, then
`lawradar serve --host 0.0.0.0 --port $PORT --token ...`). Limits:

- SQLite lives on local disk - **snapshot and verify it** with
  `lawradar backup create --keep 14`; free-tier ephemeral disks wipe it
  on redeploy. See `docs/backup.md`. Postgres migration is future work
  (repository layer is isolated in `db/store.py`).
- Free quotas change; the product must remain usable locally (Option A)
  if hosting lapses.
- Put TLS + real authentication (reverse proxy) in front. The
  `--token` is a shared secret, not user accounts.

## Backups (M10)

SQLite is the only datastore; treat the DB file as the product.

```powershell
lawradar backup create --keep 14      # data/backups/lawradar-<UTC>.db + .sha256 + .json
lawradar backup verify data\backups\lawradar-<UTC>.db   # exit 1 = do not trust
lawradar backup restore data\backups\lawradar-<UTC>.db --force
```

`create` is safe while the server/watch runs (SQLite online backup API).
`restore` fails closed while `serve` or `watch` holds the runtime lock;
stopping them first is mandatory. It writes a `lawradar-pre-restore-*`
safety snapshot before replacing the database. Schedule creation daily and
copy all three files (`.db`, `.sha256`, `.json`) off-host - a partial copy
will fail verification by design. Details and a restore drill:
`docs/backup.md`. Backups are **not encrypted**; protect them like the DB.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LAWRADAR_DATA_DIR` | runtime data | `./data` |
| `LAWRADAR_DB_URL` | sqlite only | `sqlite:///./data/lawradar.db` |
| `LAWRADAR_LOG_LEVEL` / `_LOG_FILE` | logging | `INFO` / stdout |
| `LAWRADAR_REVIEW_POLICY` | only `manual` | `manual` |
| `LAWRADAR_AI_ENABLED` / `_AI_COMMAND` | optional summariser | `false` / empty |
| `LAWRADAR_POST_LIMIT_PER_MINUTE` | POST rate limit | `30` |
| `LAWRADAR_CONFIG` | alternate settings file | `config/settings.yaml` |

No secrets are required for local use. Never commit `.env`,
`config/settings.yaml`, `config/sources.yaml`, or `data/`.
