"""Cross-process reader/writer lock for database replacement.

``serve`` and ``watch`` hold a shared runtime lock; ``backup restore``
needs the exclusive lock. Readers may coexist, but a restore fails closed
while either is running. This prevents POSIX split-brain, where replacing
a database beneath an open connection succeeds and the old process keeps
writing to an unlinked inode.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


class LockBusy(RuntimeError):
    """Another process holds an incompatible database lock."""


def lock_path(db_path: str | Path) -> Path:
    target = Path(db_path)
    return target.with_name(target.name + ".lock")


def _posix_lock(handle, shared: bool) -> None:
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    try:
        fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
    except OSError as exc:
        raise LockBusy(
            "database is in use by another process; stop serve/watch "
            "before restoring") from exc


def _windows_lock(handle, shared: bool) -> tuple:
    """Return the OVERLAPPED state that must stay alive while locked."""
    import ctypes
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    kernel32.LockFileEx.restype = wintypes.BOOL
    kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(Overlapped)]
    kernel32.UnlockFileEx.restype = wintypes.BOOL
    overlapped = Overlapped()
    flags = 0x1  # LOCKFILE_FAIL_IMMEDIATELY
    if not shared:
        flags |= 0x2  # LOCKFILE_EXCLUSIVE_LOCK
    os_handle = handle.fileno()
    import msvcrt
    native = msvcrt.get_osfhandle(os_handle)
    if not kernel32.LockFileEx(native, flags, 0, 1, 0,
                               ctypes.byref(overlapped)):
        raise LockBusy(
            "database is in use by another process; stop serve/watch "
            "before restoring")
    return kernel32, native, overlapped


def _windows_unlock(state: tuple) -> None:
    import ctypes

    kernel32, native, overlapped = state
    kernel32.UnlockFileEx(native, 0, 1, 0, ctypes.byref(overlapped))


@contextmanager
def _db_lock(db_path: str | Path, *, shared: bool):
    path = lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        state = None
        if fcntl is not None:
            _posix_lock(handle, shared)
        else:  # pragma: no cover - exercised on Windows
            state = _windows_lock(handle, shared)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows
                _windows_unlock(state)


@contextmanager
def runtime_lock(db_path: str | Path):
    """Shared lock for long-running readers (``serve``/``watch``)."""
    with _db_lock(db_path, shared=True):
        yield


@contextmanager
def exclusive_lock(db_path: str | Path):
    """Exclusive lock for destructive replacement (``backup restore``)."""
    with _db_lock(db_path, shared=False):
        yield
