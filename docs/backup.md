# Backups and restore (Milestone 10)

SQLite is the only datastore in this MVP. A lost `data/lawradar.db` means
lost documents, reports, review history, and feedback, so treat snapshots
as part of operating the tool. All commands are local, stdlib-only, and
never touch the network.

## What a backup is

`lawradar backup create` writes three files together in `data/backups/`
(or `--out DIR`):

```text
lawradar-20261027T063000Z.db       consistent SQLite snapshot
lawradar-20261027T063000Z.db.sha256  sha256sum-compatible checksum
lawradar-20261027T063000Z.db.json    manifest (counts, migrations, source)
```

The `.db` is copied with SQLite's online backup API, so taking one while
`lawradar serve` or `lawradar watch` is running does not produce a torn
file. The checksum is what later makes tampering or a truncated copy
visible; the manifest records the row counts and applied migrations so a
restore can be compared against the original.

Keep all three files together. A `.db` without its `.sha256` is not
restorable through this tool, by design.

## Create and verify

```powershell
# Default location: data/backups; keep the 14 newest lawradar-* snapshots
lawradar backup create --keep 14

# Prove the newest file is internally consistent before trusting it
lawradar backup verify data\backups\lawradar-20261027T063000Z.db
```

`verify` exits non-zero unless every check passes:

- the `.sha256` sidecar exists, is well formed, and matches the file
- the `.json` manifest exists and has the same hash, size, name, counts,
  and migrations
- SQLite `PRAGMA integrity_check` returns exactly `ok`
- `PRAGMA foreign_key_check` reports no violations
- the required lawradar tables and `_migrations` rows are present

Exit 1 means **do not restore**. Re-copy the three files from their
off-host location, or choose an older snapshot that verifies.

## Restore

Stop `lawradar serve` and `lawradar watch` first. Restoring under open
connections is not supported.

```powershell
lawradar backup verify data\backups\lawradar-20261027T063000Z.db
lawradar backup restore data\backups\lawradar-20261027T063000Z.db --force
```

`restore` verifies the snapshot again, writes a
`lawradar-pre-restore-<UTC>.db` safety backup of the current database
(with the same `.sha256` and `.json` sidecars), copies the snapshot to a
partial file, re-checks its SHA-256 and structure, and swaps it into place
atomically. Stale
`-wal`/`-shm`/`-journal` files beside the target are removed so they
cannot replay old pages into the restored file. If the current database is too corrupt
to snapshot safely, the tool preserves it as
`lawradar-pre-restore-unverified-<UTC>.db` (no sidecars) and still restores
the verified backup. Without `--force` it refuses to overwrite an existing
database.

After a restore, run:

```powershell
lawradar health
lawradar sources health
lawradar eval
```

`sources health` may report `due`/`stale` because timestamps move back in
time; the next sweep fixes that. It is not evidence the restore failed.

## Schedule and offsite copies

Daily is enough for a single-operator pilot; keep more snapshots before
pilot demos or bulk imports.

Windows Task Scheduler (daily 06:00, separate from the sweep task):

```powershell
schtasks /Create /SC DAILY /ST 06:00 /TN "IndiaLawRadar backup" `
  /TR "cmd /c cd C:\path\to\india-law-radar && .venv\Scripts\lawradar.exe backup create --keep 14 >> data\backup.log 2>&1"
```

cron:

```cron
0 6 * * * cd /opt/india-law-radar && lawradar backup create --keep 14 >> data/backup.log 2>&1
```

Copy the whole `data/backups/` set to storage that is not the same disk
(another machine, encrypted object storage, or an external drive). A
snapshot on the failing disk is not a backup. Backups are **not
encrypted** and contain extracted legal text plus review notes - protect
them with the same access controls as the live DB.

## Restore drill

Do this once before relying on the schedule, and repeat after schema or
storage changes:

1. `lawradar backup create` and `lawradar backup verify` the new file.
2. Copy the DB aside, then delete a test row (or use a scratch data dir).
3. Stop `serve`/`watch`; run `backup restore <file> --force`.
4. Confirm `lawradar health`, `sources health`, `eval`, and the dashboard
   counts. Keep the `lawradar-pre-restore-*` file until satisfied.

## Failure modes

| Symptom | Meaning / action |
|---|---|
| `database not found` | Wrong `--data-dir`/DB path, or `lawradar init` never ran |
| `not a lawradar database` | The file is not an initialised lawradar DB; do not restore it |
| `checksum mismatch` | Tampered or partially copied file; replace all three files |
| `checksum sidecar missing` | Only the `.db` was copied; retrieve the sidecars |
| `manifest ... does not match` | Mismatched sidecars or post-creation edit; reject the set |
| `target exists ... without --force` | Expected guard; stop writers, confirm target, repeat with `--force` |
| `database is in use` / `database is locked` / access denied | A server, watch loop, or viewer still holds the file; stop it and retry (restore takes the exclusive runtime lock) |
| `restore failed` after partial copy | The target was not replaced; inspect the error and retry after freeing locks |

## Limits

- No point-in-time recovery, replication, or encryption: one snapshot per
  run, taken when you run it. Checksums are unkeyed - they detect
  corruption and partial copies, not an attacker who can rewrite the DB
  and both sidecars; protect the directory with filesystem ACLs.
- Backups do not include `.env`, `config/settings.yaml`,
  `config/sources.yaml`, raw/text corpora under `data/raw` and
  `data/text`, or logs. Back those up separately if you need them.
- Retention only prunes files matching `lawradar-<UTC>.db`; pre-restore
  safety snapshots and unrelated files are left alone.
- A manifest stores the absolute source path for operator context, not
  for portability. Verification does not depend on that path.
