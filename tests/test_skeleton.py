import pytest

from app import config, db


def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Mockup Maker" in response.text


def test_database_file_created_on_startup(db_path, client):
    assert db_path.exists()


def test_database_path_is_relative_to_project_root(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "data/other.db")
    assert config.database_path() == config.ROOT_DIR / "data" / "other.db"


def test_unset_environment_means_development(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert config.environment() == "development"
    assert not config.is_production()


def test_invalid_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    with pytest.raises(ValueError):
        config.environment()


def test_migrations_apply_once_and_upgrade_in_place(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    monkeypatch.setattr(db, "MIGRATIONS", ["CREATE TABLE a (id INTEGER PRIMARY KEY);"])
    db.init(path)
    assert db.schema_version(path) == 1

    conn = db.connect(path)
    with conn:
        conn.execute("INSERT INTO a (id) VALUES (1)")
    conn.close()

    monkeypatch.setattr(db, "MIGRATIONS", [
        "CREATE TABLE a (id INTEGER PRIMARY KEY);",
        "CREATE TABLE b (id INTEGER PRIMARY KEY);",
    ])
    db.init(path)
    assert db.schema_version(path) == 2

    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM a").fetchone()[0] == 1
    conn.close()
