import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.api.main import app  # noqa: E402 — must follow env var setup above
from tenderai_bf.db import Base, get_db  # noqa: E402 — must follow env var setup above


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  # noqa: N806 — SQLAlchemy idiom for a session factory
    session = SessionLocal()
    yield session, engine
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(test_db):
    session, engine = test_db

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_headers(client: TestClient) -> dict:
    """Create a test admin JWT directly."""
    from tenderai_bf.api.dependencies import create_access_token

    token = create_access_token({"sub": "testadmin", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def test_get_all_settings_returns_sections(client):
    headers = _auth_headers(client)
    res = client.get("/api/v1/admin/settings", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "sections" in body
    assert "readonly" in body


def test_get_section_returns_404_when_absent(client):
    headers = _auth_headers(client)
    res = client.get("/api/v1/admin/settings/pipeline", headers=headers)
    assert res.status_code == 404


def test_put_section_validates_and_saves(client, test_db):
    session, _ = test_db
    headers = _auth_headers(client)
    payload = {
        "max_items_per_run": 200,
        "min_relevance_score": 0.6,
        "deduplication_threshold": 0.8,
        "deduplication_method": "hash_similarity",
        "use_llm_classification": True,
        "pdf_timeout": 60,
        "max_file_size_mb": 100,
    }
    res = client.put("/api/v1/admin/settings/pipeline", json=payload, headers=headers)
    assert res.status_code == 200

    from tenderai_bf.settings_store import SettingsStore

    saved = SettingsStore.get_section(session, "pipeline")
    assert saved["min_relevance_score"] == 0.6
    assert saved["max_items_per_run"] == 200


def test_put_section_rejects_invalid_payload(client):
    headers = _auth_headers(client)
    payload = {"min_relevance_score": 99.0}  # > 1.0, invalid
    res = client.put("/api/v1/admin/settings/pipeline", json=payload, headers=headers)
    assert res.status_code == 422


def test_put_unknown_section_returns_400(client):
    headers = _auth_headers(client)
    res = client.put("/api/v1/admin/settings/nonexistent", json={}, headers=headers)
    assert res.status_code == 400


def test_seed_endpoint_inserts_sections(client, test_db):
    session, _ = test_db
    headers = _auth_headers(client)
    res = client.post("/api/v1/admin/settings/seed", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert "seeded" in body
    assert len(body["seeded"]) == 7


def test_get_settings_requires_auth(client):
    res = client.get("/api/v1/admin/settings")
    assert res.status_code == 401
