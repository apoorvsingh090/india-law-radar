"""Structured logging for India Law Radar (stdlib only, no paid services)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO", log_file: str = "") -> logging.Logger:
    """Configure root logging once and return the app logger.

    Safe to call multiple times (idempotent for repeated CLI invocations
    and tests).
    """
    global _CONFIGURED
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    if not _CONFIGURED:
        handler: logging.Handler
        if log_file:
            path = Path(log_file)
            if path.parent and str(path.parent) not in ("", "."):
                path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
        else:
            handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.handlers.clear()
        root.addHandler(handler)
        _CONFIGURED = True
    else:
        root.setLevel(numeric)
        for handler in root.handlers:
            handler.setLevel(numeric)
    logger = logging.getLogger("lawradar")
    logger.debug("logging configured (level=%s, file=%s)", level, log_file or "-")
    return logger


def get_logger(name: str = "lawradar") -> logging.Logger:
    return logging.getLogger(name)


def reset_for_tests() -> None:  # pragma: no cover - test helper
    """Reset logging configuration (used only in tests)."""
    global _CONFIGURED
    _CONFIGURED = False
    logging.getLogger().handlers.clear()
