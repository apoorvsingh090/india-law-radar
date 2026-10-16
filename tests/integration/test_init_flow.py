"""End-to-end M1 flow: init -> health -> pytest-cleanliness, no network."""
from lawradar.cli import main
from lawradar.config import load_settings


def test_init_then_health_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    assert main(["--data-dir", str(data), "init", "--force"]) == 0
    assert data.is_dir()
    config = load_settings()
    assert config is not None
    assert main(["--data-dir", str(data), "health"]) == 0
