"""Tests for company_id JWT claim and cross-company scoping."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, Company, User


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


@pytest.fixture
def two_companies(db_session):
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    test_co = Company(name="Test Co", slug="test-co", active=True)
    db_session.add_all([yulcom, test_co])
    db_session.commit()
    return yulcom, test_co


def _login(client, username, password):
    resp = client.post(
        "/api/v1/admin/login/simple", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_login_jwt_includes_company_id(client, db_session, two_companies):
    yulcom, _ = two_companies
    user = User(
        id=str(uuid.uuid4()),
        username="yulcom_admin",
        email="yulcom_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=yulcom.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(user)
    db_session.commit()

    token = _login(client, "yulcom_admin", "pass12345")

    resp = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # /me's UserResponse doesn't carry company_id today — this test decodes
    # the token directly to check the claim, which is the actual contract.
    from jose import jwt

    from tenderai_bf.api.dependencies import ALGORITHM, SECRET_KEY

    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["company_id"] == yulcom.id


def test_login_jwt_company_id_null_for_super_admin(client, db_session):
    user = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="super_admin",
        company_id=None,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(user)
    db_session.commit()

    token = _login(client, "root", "pass12345")

    from jose import jwt

    from tenderai_bf.api.dependencies import ALGORITHM, SECRET_KEY

    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["company_id"] is None
