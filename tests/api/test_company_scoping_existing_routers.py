"""Tests for company_id scoping added to recipients/runs/users, and removal
of the YULCOM-hardcoded stopgaps."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, Company, Country, Recipient, User


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)  # noqa: N806 — SQLAlchemy idiom for a session factory
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    resp = client.post(
        "/api/v1/admin/login/simple", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_recipient_created_by_company_admin_gets_own_company_id(client, db_session):
    company = Company(name="Test Co", slug="test-co", active=True)
    country = Country(name="Canada", code="CA", locale="fr")
    db_session.add_all([company, country])
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="testco_admin",
        email="testco_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()

    token = _login(client, "testco_admin", "pass12345")

    resp = client.post(
        "/api/v1/recipients",
        json={
            "email": "someone@test-co.com",
            "name": "Someone",
            "group": "to",
            "enabled": True,
            "country_id": country.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] == company.id  # not hardcoded to YULCOM


def test_recipients_list_filtered_to_own_company(client, db_session):
    company_a = Company(name="Company A", slug="company-a", active=True)
    company_b = Company(name="Company B", slug="company-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    db_session.add_all(
        [
            Recipient(email="a@a.com", group="to", enabled=True, company_id=company_a.id),
            Recipient(email="b@b.com", group="to", enabled=True, company_id=company_b.id),
        ]
    )
    admin_a = User(
        id=str(uuid.uuid4()),
        username="admin_a",
        email="admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin_a)
    db_session.commit()

    token = _login(client, "admin_a", "pass12345")

    resp = client.get(
        "/api/v1/recipients", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    emails = [r["email"] for r in resp.json()["recipients"]]
    assert emails == ["a@a.com"]


def test_create_company_admin_user_requires_company_id(client, db_session):
    root = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(root)
    db_session.commit()
    token = _login(client, "root", "rootpass123")

    resp = client.post(
        "/api/v1/users",
        json={
            "username": "newcompanyadmin",
            "email": "newcompanyadmin@test.com",
            "role": "company_admin",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_super_admin_manual_trigger_defaults_to_yulcom(client, db_session, monkeypatch):
    """The exact regression this task must not reintroduce: today's live
    admin account is super_admin, and clicking "Lancer maintenant" must
    keep delivering to YULCOM by default when no company_id is given."""
    from tenderai_bf.models import Country

    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    country = Country(name="Burkina Faso", code="BF", locale="fr")
    db_session.add_all([yulcom, country])
    db_session.commit()

    root = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(root)
    db_session.commit()
    token = _login(client, "root", "rootpass123")

    from unittest.mock import MagicMock

    from tenderai_bf.agents import get_delivery_pipeline

    fake_result = MagicMock(error_occurred=False, warnings=[])
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return fake_result

    monkeypatch.setattr(get_delivery_pipeline(), "run", fake_run)

    resp = client.post(
        f"/api/v1/admin/countries/{country.id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert resp.json()["company_id"] == yulcom.id


def test_company_admin_cannot_trigger_delivery_for_another_company(
    client, db_session
):
    from tenderai_bf.models import Country

    own_company = Company(name="Own Co", slug="own-co", active=True)
    other_company = Company(name="Other Co", slug="other-co", active=True)
    country = Country(name="Burkina Faso", code="BF", locale="fr")
    db_session.add_all([own_company, other_company, country])
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="own_admin",
        email="own_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=own_company.id,
        country_id=country.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()
    token = _login(client, "own_admin", "pass12345")

    resp = client.post(
        f"/api/v1/admin/countries/{country.id}/run?company_id={other_company.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
