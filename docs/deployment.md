# Deployment (Milestone 7 public beta)

The app stays usable locally with no paid service. Anything beyond
loopback needs the guards below — there is no multi-user auth model.

## Option A — local loopback (default, safest)

```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install .
lawradar init
lawradar serve            # http://127.0.0.1:8080
```

Review POSTs are open on loopback by design (single operator machine).
No token needed; nothing is reachable from the network.

## Option B — LAN / small team (token required)

```powershell
$env:LAWRADAR_POST_LIMIT_PER_MINUTE = "30"
lawradar serve --host 0.0.0.0 --port 8080 --token "<long-random-secret>"
```

`serve` refuses non-loopback binds without `--token`. Share the token
out of band. POSTs (reviews, feedback) require it as a form field;
rates are limited per client IP (`post_limit_per_minute`, default 30).

## Option C — always-on host (experimental)

Any Python host works (buildpack-style: `pip install .`, then
`lawradar serve --host 0.0.0.0 --port $PORT --token ...`). Limits:

- SQLite lives on local disk — **back it up** (`data/lawradar.db`);
  free-tier ephemeral disks wipe it on redeploy. Postgres migration is
  future work (repository layer is isolated in `db/store.py`).
- Free quotas change; the product must remain usable locally (Option A)
  if hosting lapses.
- Put TLS + real authentication (reverse proxy) in front. The
  `--token` is a shared secret, not user accounts.

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
