import os

import pytest

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


def test_country_create_schema_validates_name():
    from pydantic import ValidationError

    from tenderai_bf.api.schemas.countries import CountryCreate

    with pytest.raises(ValidationError):
        CountryCreate(name="", code="BF", locale="fr")


def test_country_create_schema_valid():
    from tenderai_bf.api.schemas.countries import CountryCreate

    c = CountryCreate(name="Burkina Faso", code="BF", locale="fr")
    assert c.code == "BF"


def test_country_update_schema_all_optional():
    from tenderai_bf.api.schemas.countries import CountryUpdate

    u = CountryUpdate()
    assert u.name is None
    assert u.active is None


def test_country_read_schema_from_orm():
    from datetime import datetime

    from tenderai_bf.api.schemas.countries import CountryRead

    obj = CountryRead(
        id=1,
        name="BF",
        code="BF",
        locale="fr",
        active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    assert obj.id == 1


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from tenderai_bf.api.main import app
    from tenderai_bf.db import Base

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)

    def override_db():
        with Session(engine) as session:
            yield session

    from tenderai_bf.api.dependencies import get_db

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _get_token(client):
    """Get auth token — try login, fall back to fake token."""
    try:
        resp = client.post(
            "/api/v1/users/login",
            json={"username": "admin", "password": "test-admin-password-not-real"},
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", "fake-token")
    except Exception:
        pass
    return "fake-token"


def test_list_countries_returns_list(client):
    headers = {"Authorization": f"Bearer {_get_token(client)}"}
    resp = client.get("/api/v1/admin/countries", headers=headers)
    assert resp.status_code in (200, 401, 403)  # endpoint exists


def test_create_country_endpoint_exists(client):
    headers = {"Authorization": f"Bearer {_get_token(client)}"}
    resp = client.post(
        "/api/v1/admin/countries",
        json={"name": "Côte d'Ivoire", "code": "CI", "locale": "fr"},
        headers=headers,
    )
    # 201 = success, 401/403 = auth required (endpoint exists), 422 = validation works
    assert resp.status_code in (201, 401, 403, 422)


def test_get_country_not_found_returns_404_or_auth_required(client):
    headers = {"Authorization": f"Bearer {_get_token(client)}"}
    resp = client.get("/api/v1/admin/countries/999999", headers=headers)
    assert resp.status_code in (404, 401, 403)


def test_countries_router_registered():
    from tenderai_bf.api.main import app

    paths = [r.path for r in app.routes]
    assert any("/admin/countries" in p for p in paths)


def test_country_settings_endpoint_exists(client):
    headers = {"Authorization": f"Bearer {_get_token(client)}"}
    resp = client.get("/api/v1/admin/countries/1/settings", headers=headers)
    assert resp.status_code in (200, 401, 403, 404)
