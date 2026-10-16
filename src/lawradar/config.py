"""Configuration loading for India Law Radar.

Milestone 1: YAML file + environment-variable overrides, safe local defaults.
No secrets required for the local MVP.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

APP_NAME = "india-law-radar"

DEFAULTS: dict = {
    "app_name": APP_NAME,
    "environment": "local",
    "data_dir": "./data",
    "db_url": "sqlite:///./data/lawradar.db",
    "log_level": "INFO",
    "log_file": "",
    "poll_default_minutes": 1440,
    "http_timeout_seconds": 30,
    "http_max_bytes": 50_000_000,
}

ENV_MAP = {
    "LAWRADAR_ENV": "environment",
    "LAWRADAR_DATA_DIR": "data_dir",
    "LAWRADAR_DB_URL": "db_url",
    "LAWRADAR_LOG_LEVEL": "log_level",
    "LAWRADAR_LOG_FILE": "log_file",
    "LAWRADAR_CONFIG": None,  # path to config file itself, handled separately
}


@dataclass
class AppConfig:
    environment: str = "local"
    data_dir: str = "./data"
    db_url: str = "sqlite:///./data/lawradar.db"
    log_level: str = "INFO"
    log_file: str = ""
    poll_default_minutes: int = 1440
    http_timeout_seconds: int = 30
    http_max_bytes: int = 50_000_000
    config_path: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "data_dir": self.data_dir,
            "db_url": self.db_url,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "poll_default_minutes": self.poll_default_minutes,
            "http_timeout_seconds": self.http_timeout_seconds,
            "http_max_bytes": self.http_max_bytes,
        }


def find_config_file(explicit: str | None = None) -> Path | None:
    """Return the config file to use, or None for defaults-only."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("LAWRADAR_CONFIG", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("config/settings.yaml"))
    candidates.append(Path("config/settings.example.yaml"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _load_yaml(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError(
            "pyyaml is required to load configuration. Install with: pip install pyyaml"
        )
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at top level")
    return data


def load_settings(explicit: str | None = None) -> AppConfig:
    """Load settings from YAML file (if present) with env-var overrides."""
    merged: dict = dict(DEFAULTS)
    config_path = find_config_file(explicit)
    file_data: dict = {}
    if config_path is not None:
        file_data = _load_yaml(config_path)
        for key, value in file_data.items():
            if key in merged:
                merged[key] = value
            # Unknown keys are preserved in extra, never silently dropped.
    for env_var, key in ENV_MAP.items():
        if key is None:
            continue
        raw = os.environ.get(env_var, "").strip()
        if raw:
            merged[key] = raw
    # Coerce numeric fields that may arrive as strings from env vars.
    for int_key in ("poll_default_minutes", "http_timeout_seconds", "http_max_bytes"):
        try:
            merged[int_key] = int(merged[int_key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid integer for {int_key}: {merged[int_key]!r}") from exc
    known = set(AppConfig.__dataclass_fields__) - {"config_path", "extra"}
    extra = {k: v for k, v in file_data.items() if k not in DEFAULTS}
    return AppConfig(
        **{k: merged[k] for k in known},
        config_path=str(config_path) if config_path else "",
        extra=extra,
    )


def ensure_data_dir(config: AppConfig) -> Path:
    """Create the data directory if missing. Returns the resolved path."""
    path = Path(config.data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
