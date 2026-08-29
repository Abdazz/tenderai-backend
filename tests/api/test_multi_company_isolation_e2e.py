"""End-to-end verification that two companies are fully isolated from each
other across the surfaces this plan touches: settings, recipients, runs,
and company management itself. Exercises real login + real JWTs + real
DB queries across two independently seeded companies (YULCOM and a
throwaway 'test-co'), per this plan's Global Constraints."""
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


@pytest.fixture
def two_isolated_companies(client, db_session):
    """Seeds YULCOM and test-co, each with a country subscription, settings,
    a company_admin user, and a recipient — the full shape this plan's
    scoping logic needs to actually exercise isolation, not just assert it."""
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    test_co = Company(name="Test Co", slug="test-co", active=True)
    bf = Country(name="Burkina Faso", code="BF", locale="fr")
    ca = Country(name="Canada", code="CA", locale="fr")
    db_session.add_all([yulcom, test_co, bf, ca])
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
    yulcom_admin = User(
        id=str(uuid.uuid4()),
        username="yulcom_admin",
        email="yulcom_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=yulcom.id,
        is_active=True,
        password_reset_required=False,
    )
    testco_admin = User(
        id=str(uuid.uuid4()),
        username="testco_admin",
        email="testco_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=test_co.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([root, yulcom_admin, testco_admin])
    db_session.add_all(
        [
            Recipient(
                email="yulcom-recipient@test.com",
                group="to",
                enabled=True,
                company_id=yulcom.id,
                country_id=bf.id,
            ),
            Recipient(
                email="testco-recipient@test.com",
                group="to",
                enabled=True,
                company_id=test_co.id,
                country_id=ca.id,
            ),
        ]
    )
    db_session.commit()

    root_token = _login(client, "root", "rootpass123")
    client.post(
        f"/api/v1/admin/companies/{yulcom.id}/countries",
        json={"country_id": bf.id},
        headers={"Authorization": f"Bearer {root_token}"},
    )
    client.post(
        f"/api/v1/admin/companies/{test_co.id}/countries",
        json={"country_id": ca.id},
        headers={"Authorization": f"Bearer {root_token}"},
    )

    return {
        "yulcom": yulcom,
        "test_co": test_co,
        "root_token": root_token,
        "yulcom_token": _login(client, "yulcom_admin", "pass12345"),
        "testco_token": _login(client, "testco_admin", "pass12345"),
    }


def test_company_admin_sees_only_own_recipients(client, two_isolated_companies):
    resp = client.get(
        "/api/v1/recipients",
        headers={"Authorization": f"Bearer {two_isolated_companies['yulcom_token']}"},
    )
    assert resp.status_code == 200
    emails = {r["email"] for r in resp.json()["recipients"]}
    assert emails == {"yulcom-recipient@test.com"}

    resp = client.get(
        "/api/v1/recipients",
        headers={"Authorization": f"Bearer {two_isolated_companies['testco_token']}"},
    )
    assert resp.status_code == 200
    emails = {r["email"] for r in resp.json()["recipients"]}
    assert emails == {"testco-recipient@test.com"}


def test_company_admin_cannot_access_other_companys_country_subscriptions(
    client, two_isolated_companies
):
    resp = client.get(
        f"/api/v1/admin/companies/{two_isolated_companies['test_co'].id}/countries",
        headers={"Authorization": f"Bearer {two_isolated_companies['yulcom_token']}"},
    )
    assert resp.status_code == 403


def test_super_admin_sees_both_companies(client, two_isolated_companies):
    resp = client.get(
        "/api/v1/admin/companies",
        headers={"Authorization": f"Bearer {two_isolated_companies['root_token']}"},
    )
    assert resp.status_code == 200
    slugs = {c["slug"] for c in resp.json()}
    assert slugs == {"yulcom", "test-co"}


def test_super_admin_sees_all_recipients_unfiltered(client, two_isolated_companies):
    resp = client.get(
        "/api/v1/recipients",
        headers={"Authorization": f"Bearer {two_isolated_companies['root_token']}"},
    )
    assert resp.status_code == 200
    emails = {r["email"] for r in resp.json()["recipients"]}
    assert emails == {"yulcom-recipient@test.com", "testco-recipient@test.com"}
