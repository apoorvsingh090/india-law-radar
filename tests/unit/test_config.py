"""Config loading tests (Milestone 1)."""
import os
from pathlib import Path

import pytest
import yaml

from lawradar.config import DEFAULTS, find_config_file, load_settings


def test_defaults_load_without_config_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_ENV"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    assert config.data_dir == DEFAULTS["data_dir"]
    assert config.log_level == DEFAULTS["log_level"]
    assert config.poll_default_minutes == DEFAULTS["poll_default_minutes"]


def test_example_yaml_loads():
    example = Path("config/settings.example.yaml")
    if not example.is_file():
        pytest.skip("run from repo root; example config not found")
    config = load_settings(str(example))
    assert config.data_dir
    assert config.http_timeout_seconds > 0


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(yaml.safe_dump({"data_dir": "./data", "log_level": "INFO"}),
                   encoding="utf-8")
    monkeypatch.setenv("LAWRADAR_DATA_DIR", "./custom-data")
    monkeypatch.setenv("LAWRADAR_LOG_LEVEL", "debug")
    config = load_settings(str(cfg))
    assert config.data_dir == "./custom-data"
    assert config.log_level == "debug"


def test_invalid_int_rejected(tmp_path, monkeypatch):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(yaml.safe_dump({"poll_default_minutes": "not-a-number"}),
                   encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(str(cfg))


def test_find_config_file_returns_none_in_empty_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAWRADAR_CONFIG", raising=False)
    assert find_config_file() is None


def test_ai_and_review_policy_defaults_and_env(tmp_path, monkeypatch):
    import yaml as _yaml

    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_AI_ENABLED", "LAWRADAR_AI_COMMAND",
                "LAWRADAR_REVIEW_POLICY"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    assert config.ai_enabled is False and config.review_policy == "manual"
    monkeypatch.setenv("LAWRADAR_AI_ENABLED", "true")
    assert load_settings().ai_enabled is True
    bad = tmp_path / "bad.yaml"
    bad.write_text(_yaml.safe_dump({"review_policy": "auto_publish"}),
                   encoding="utf-8")
    import pytest as _pytest

    with _pytest.raises(ValueError, match="review_policy"):
        load_settings(str(bad))
