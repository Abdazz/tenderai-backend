"""Tests for the companies CRUD/subscriptions/settings router."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, Company, Country, User


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
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
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


@pytest.fixture
def super_admin_token(client, db_session):
    user = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(user)
    db_session.commit()
    return _login(client, "root", "rootpass123")


def test_super_admin_can_create_company(client, super_admin_token):
    resp = client.post(
        "/api/v1/admin/companies",
        json={"name": "Test Co", "slug": "test-co"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "test-co"
    assert body["active"] is True


def test_company_admin_cannot_create_company(client, db_session, super_admin_token):
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    db_session.add(yulcom)
    db_session.commit()

    company_admin = User(
        id=str(uuid.uuid4()),
        username="yulcom_admin",
        email="yulcom_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=yulcom.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(company_admin)
    db_session.commit()

    token = _login(client, "yulcom_admin", "pass12345")

    resp = client.post(
        "/api/v1/admin/companies",
        json={"name": "Evil Co", "slug": "evil-co"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_company_admin_cannot_read_other_companys_settings(client, db_session):
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    test_co = Company(name="Test Co", slug="test-co", active=True)
    db_session.add_all([yulcom, test_co])
    db_session.commit()

    company_admin = User(
        id=str(uuid.uuid4()),
        username="yulcom_admin",
        email="yulcom_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=yulcom.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(company_admin)
    db_session.commit()

    token = _login(client, "yulcom_admin", "pass12345")

    resp = client.get(
        f"/api/v1/admin/companies/{test_co.id}/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_company_admin_can_read_own_settings(client, db_session):
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    db_session.add(yulcom)
    db_session.commit()

    company_admin = User(
        id=str(uuid.uuid4()),
        username="yulcom_admin",
        email="yulcom_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=yulcom.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(company_admin)
    db_session.commit()

    token = _login(client, "yulcom_admin", "pass12345")

    resp = client.get(
        f"/api/v1/admin/companies/{yulcom.id}/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_subscribe_company_to_country(client, db_session, super_admin_token):
    company = Company(name="Test Co", slug="test-co", active=True)
    country = Country(name="Canada", code="CA", locale="fr")
    db_session.add_all([company, country])
    db_session.commit()

    resp = client.post(
        f"/api/v1/admin/companies/{company.id}/countries",
        json={"country_id": country.id},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 201

    resp = client.get(
        f"/api/v1/admin/companies/{company.id}/countries",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 200
    subs = resp.json()
    assert len(subs) == 1
    assert subs[0]["country_id"] == country.id
    assert subs[0]["enabled"] is True


def test_delete_company_is_soft_delete(client, db_session, super_admin_token):
    company = Company(name="Test Co", slug="test-co", active=True)
    db_session.add(company)
    db_session.commit()
    company_id = company.id

    resp = client.delete(
        f"/api/v1/admin/companies/{company_id}",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert resp.status_code == 204

    db_session.expire_all()
    from tenderai_bf.models import Company as CompanyModel

    row = db_session.query(CompanyModel).filter(CompanyModel.id == company_id).first()
    assert row is not None  # not actually deleted
    assert row.active is False
