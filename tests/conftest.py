import pytest
from fastapi.testclient import TestClient


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
