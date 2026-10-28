"""Verifiable local SQLite backups (Milestone 10).

A backup is three files written together:

- ``lawradar-<UTC timestamp>.db`` - a consistent snapshot via SQLite's
  online backup API (safe while ingestion writes, though restore is not)
- ``.sha256`` - standard ``sha256sum`` checksum of the database bytes
- ``.json`` - manifest: timestamp, tool version, counts, migrations

Verification is read-only and fails closed: the checksum, SQLite
``integrity_check``, ``foreign_key_check``, required tables, and manifest
counts must all agree. Restore verifies first, saves a safety snapshot of
the current database, then atomically replaces it. Nothing here talks to
the network or needs a paid service.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from lawradar import __version__

BACKUP_PREFIX = "lawradar"
SAFETY_PREFIX = "lawradar-pre-restore"
MANIFEST_FORMAT = 1
LOG = logging.getLogger(__name__)

REQUIRED_TABLES = frozenset({
    "_meta", "_migrations", "sources", "documents", "document_versions",
    "change_reports", "citations", "ingestion_runs", "review_tasks",
})
COUNT_QUERIES = {
    "sources": "SELECT COUNT(*) FROM sources",
    "documents": "SELECT COUNT(*) FROM documents",
    "versions": "SELECT COUNT(*) FROM document_versions",
    "reports": "SELECT COUNT(*) FROM change_reports",
    "published_reports": (
        "SELECT COUNT(*) FROM change_reports WHERE published_at IS NOT NULL"),
    "citations": "SELECT COUNT(*) FROM citations",
    "review_tasks": "SELECT COUNT(*) FROM review_tasks",
    "runs": "SELECT COUNT(*) FROM ingestion_runs",
}
_NAME_RE = re.compile(
    r"^(?P<prefix>lawradar)-(?P<stamp>\d{8}T\d{6}Z)"
    r"(?:-(?P<seq>\d+))?\.db$")


class BackupError(RuntimeError):
    """A backup could not be created, verified, or restored safely."""


@dataclass(frozen=True)
class BackupInfo:
    path: str
    name: str
    sha256: str
    bytes: int
    created_at: str
    counts: dict[str, int]
    migrations: list[str]
    has_manifest: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _check_integrity(conn: sqlite3.Connection) -> None:
    rows = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
    if rows != ["ok"]:
        detail = "; ".join(rows[:5]) or "no result"
        raise BackupError(f"SQLite integrity check failed: {detail}")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise BackupError(
            f"foreign-key violations in backup ({len(violations)} rows)")


def _inspect(path: Path) -> tuple[dict[str, int], list[str]]:
    """Read-only structural check; returns (counts, migrations)."""
    try:
        conn = _open_ro(path)
    except sqlite3.Error as exc:
        raise BackupError(f"cannot open backup as sqlite: {exc}") from exc
    try:
        _check_integrity(conn)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise BackupError(
                "not a lawradar database (missing tables: "
                + ", ".join(missing) + ")")
        migrations = [row[0] for row in conn.execute(
            "SELECT name FROM _migrations ORDER BY name")]
        counts = {key: int(conn.execute(sql).fetchone()[0])
                  for key, sql in COUNT_QUERIES.items()}
        return counts, migrations
    except sqlite3.Error as exc:
        raise BackupError(f"cannot inspect backup: {exc}") from exc
    finally:
        conn.close()


def _backup_sort_key(path: Path) -> tuple[str, int]:
    match = _NAME_RE.fullmatch(path.name)
    if not match:
        return ("", 0)
    return (match.group("stamp"), int(match.group("seq") or 0))


def _unique_backup_path(out_dir: Path, prefix: str,
                        stamp: str) -> Path:
    """Reserve a fresh path atomically so concurrent backups cannot collide."""
    for sequence in range(1000):
        suffix = "" if sequence == 0 else f"-{sequence}"
        name = f"{prefix}-{stamp}{suffix}.db"
        candidate = out_dir / name
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    raise BackupError("cannot allocate a unique backup filename")


def _prune(out_dir: Path, keep: int, protected: Path | None = None
           ) -> list[str]:
    """Remove older snapshots, never the one just created."""
    if keep <= 0:
        return []
    protected = protected.resolve() if protected is not None else None
    files = [path for path in out_dir.glob(f"{BACKUP_PREFIX}-*.db")
             if _NAME_RE.fullmatch(path.name)
             and (protected is None or path.resolve() != protected)]
    files.sort(
        key=lambda path: (path.stat().st_mtime_ns, _backup_sort_key(path)),
        reverse=True)
    remaining_keep = max(0, keep - 1)
    removed: list[str] = []
    for path in files[remaining_keep:]:
        removed.append(path.name)
        path.unlink(missing_ok=True)
        for ext in (".sha256", ".json"):
            _sidecar(path, ext).unlink(missing_ok=True)
    return removed


def _write_metadata(path: Path, info: BackupInfo, source: Path) -> None:
    _sidecar(path, ".sha256").write_text(
        f"{info.sha256}  {path.name}\n", encoding="ascii")
    manifest = {
        "format": MANIFEST_FORMAT,
        "tool": f"lawradar/{__version__}",
        "created_at": info.created_at,
        "name": info.name,
        "sha256": info.sha256,
        "bytes": info.bytes,
        "source_database": str(source.resolve()),
        "counts": info.counts,
        "migrations": info.migrations,
    }
    _sidecar(path, ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def create_backup(db_path: str | Path, out_dir: str | Path | None = None,
                  *, prefix: str = BACKUP_PREFIX, keep: int = 0,
                  now: datetime | None = None) -> BackupInfo:
    """Create a verified snapshot. ``keep`` prunes older ``lawradar-*`` files."""
    source = Path(db_path)
    if not source.is_file():
        raise BackupError(f"database not found: {source}")
    target_dir = Path(out_dir) if out_dir is not None else source.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    dest = _unique_backup_path(target_dir, prefix,
                               moment.strftime("%Y%m%dT%H%M%SZ"))
    partial = dest.with_name(dest.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        src = sqlite3.connect(str(source))
        try:
            dst = sqlite3.connect(str(partial))
            try:
                src.backup(dst, pages=256)
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(partial, dest)
        digest = sha256_file(dest)
        size = dest.stat().st_size
        counts, migrations = _inspect(dest)
        info = BackupInfo(
            path=str(dest.resolve()), name=dest.name, sha256=digest,
            bytes=size, created_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            counts=counts, migrations=migrations)
        _write_metadata(dest, info, source)
    except (OSError, sqlite3.Error, BackupError) as exc:
        partial.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        for ext in (".sha256", ".json"):
            _sidecar(dest, ext).unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"backup failed: {exc}") from exc
    try:
        _prune(target_dir, keep, protected=dest)
    except OSError as exc:
        LOG.warning("backup created but retention failed: %s", exc)
    return info


def verify_backup(path: str | Path) -> BackupInfo:
    """Fail closed unless checksum, manifest, schema, and integrity agree."""
    backup = Path(path)
    if not backup.is_file():
        raise BackupError(f"backup not found: {backup}")
    sha_path = _sidecar(backup, ".sha256")
    if not sha_path.is_file():
        raise BackupError(
            f"checksum sidecar missing: {sha_path.name} (cannot verify)")
    parts = sha_path.read_text(encoding="ascii", errors="replace").split()
    if not parts or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise BackupError(f"malformed checksum sidecar: {sha_path.name}")
    expected = parts[0].lower()
    actual = sha256_file(backup)
    if actual != expected:
        raise BackupError(
            f"checksum mismatch for {backup.name} "
            f"(expected {expected[:12]}, got {actual[:12]})")
    size = backup.stat().st_size
    manifest_path = _sidecar(backup, ".json")
    if not manifest_path.is_file():
        raise BackupError(
            f"manifest sidecar missing: {manifest_path.name} (cannot verify)")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"malformed manifest {manifest_path.name}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BackupError(f"malformed manifest {manifest_path.name}")
    if manifest.get("format") != MANIFEST_FORMAT:
        raise BackupError(
            f"unsupported manifest format: {manifest.get('format')!r}")
    if str(manifest.get("sha256", "")).lower() != actual:
        raise BackupError("manifest checksum does not match the backup")
    if manifest.get("bytes") is not None and manifest["bytes"] != size:
        raise BackupError("manifest size does not match the backup")
    if manifest.get("name") and manifest["name"] != backup.name:
        raise BackupError("manifest filename does not match the backup")
    counts, migrations = _inspect(backup)
    if manifest.get("counts") not in (None, counts):
        raise BackupError("manifest counts do not match the backup")
    if manifest.get("migrations") not in (None, migrations):
        raise BackupError("manifest migrations do not match the backup")
    created_at = (manifest.get("created_at")
                  or datetime.fromtimestamp(
                      backup.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return BackupInfo(
        path=str(backup.resolve()), name=backup.name, sha256=actual,
        bytes=size, created_at=str(created_at), counts=counts,
        migrations=migrations, has_manifest=True)


def _raw_safety_copy(target: Path, out_dir: Path, moment: datetime) -> str:
    """Preserve an unreadable target before restore (best-effort evidence).

    Used only when the current DB cannot be verifiably backed up, so the
    copy deliberately has no sidecars: it is evidence, not a trusted backup.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_backup_path(
        out_dir, f"{SAFETY_PREFIX}-unverified",
        moment.strftime("%Y%m%dT%H%M%SZ"))
    try:
        shutil.copy2(target, dest)
        for ext in ("-wal", "-shm", "-journal"):
            side = target.with_name(target.name + ext)
            if side.is_file():
                shutil.copy2(side, dest.with_name(dest.name + ext))
    except OSError:
        dest.unlink(missing_ok=True)
        raise
    return str(dest.resolve())


def restore_backup(backup_path: str | Path, target_path: str | Path,
                   *, force: bool = False,
                   safety_dir: str | Path | None = None) -> dict:
    """Verify, snapshot the current DB, then atomically restore the backup.

    ``lawradar serve`` and ``lawradar watch`` hold the same runtime lock,
    so a restore fails closed while either is running.
    """
    from lawradar.db.lock import LockBusy, exclusive_lock

    backup = Path(backup_path)
    target = Path(target_path)
    if backup.resolve() == target.resolve():
        raise BackupError("backup and target are the same file")
    if target.exists() and not force:
        raise BackupError(
            f"target exists: {target} (refusing to overwrite without --force)")
    info = verify_backup(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with exclusive_lock(target):
            if target.exists() and not force:
                raise BackupError(
                    f"target exists: {target} "
                    "(refusing to overwrite without --force)")
            return _restore_locked(
                backup, target, info, safety_dir=safety_dir)
    except LockBusy as exc:
        raise BackupError(str(exc)) from exc


def _restore_locked(backup: Path, target: Path, info: BackupInfo, *,
                    safety_dir: str | Path | None) -> dict:
    safety: str | None = None
    if target.exists():
        safety_dir = safety_dir or target.parent / "backups"
        try:
            safety_info = create_backup(
                target, out_dir=safety_dir, prefix=SAFETY_PREFIX)
            safety = safety_info.path
        except BackupError:
            safety = _raw_safety_copy(
                target, Path(safety_dir), datetime.now(UTC))
    fd, partial_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".restore-partial",
        dir=target.parent)
    os.close(fd)
    partial = Path(partial_name)
    try:
        src = _open_ro(backup)
        try:
            dst = sqlite3.connect(str(partial))
            try:
                src.backup(dst, pages=256)
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()
        if sha256_file(partial) != info.sha256:
            raise BackupError(
                "restored copy checksum mismatch (backup changed after verify)")
        counts, migrations = _inspect(partial)
        os.replace(partial, target)
    except (OSError, sqlite3.Error, BackupError) as exc:
        partial.unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"restore failed: {exc}") from exc
    for ext in ("-wal", "-shm", "-journal"):
        sidecar = target.with_name(target.name + ext)
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            LOG.warning("restore succeeded but could not remove %s: %s",
                        sidecar.name, exc)
    return {
        "restored_from": info.path,
        "target": str(target.resolve()),
        "sha256": info.sha256,
        "counts": counts,
        "migrations": migrations,
        "safety_backup": safety,
    }
