import pytest
from fastapi.testclient import TestClient

# app/config.py loads the developer's .env; none of these may reach a test (#24).
LOCAL_SETTINGS = ("TRACKER_URL", "TRACKER_PUBLIC_URL", "TRACKER_POINTS", "TRACKER_TIMEOUT",
                  "CODEX_BIN", "CODEX_HOME", "AI_MODEL", "AI_REASONING", "AI_TIMEOUT", "PORT")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Every test starts on the stand-in AI with no tracker, whatever the local .env says.
    A test that needs a setting sets it itself."""
    monkeypatch.setenv("AI_PROVIDER", "mock")
    for name in LOCAL_SETTINGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("ENVIRONMENT", "test")
    return path


@pytest.fixture
def client(db_path):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
