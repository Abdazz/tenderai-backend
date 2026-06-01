"""Tests for user management endpoints."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, User


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
    Session = sessionmaker(bind=db_engine)
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


@pytest.fixture
def admin_token(client, db_session):
    """Create an admin user and return its JWT token."""
    admin = User(
        id=str(uuid.uuid4()),
        username="admin",
        email="admin@test.com",
        hashed_password=get_password_hash("adminpass123"),
        role="admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()

    resp = client.post(
        "/api/v1/admin/login/simple",
        json={"username": "admin", "password": "adminpass123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_list_users_requires_admin(client, admin_token):
    resp = client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["users"], list)


def test_list_users_forbidden_for_viewer(client, db_session):
    viewer = User(
        id=str(uuid.uuid4()),
        username="viewer1",
        email="viewer@test.com",
        hashed_password=get_password_hash("viewerpass123"),
        role="viewer",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(viewer)
    db_session.commit()

    resp = client.post(
        "/api/v1/admin/login/simple",
        json={"username": "viewer1", "password": "viewerpass123"},
    )
    token = resp.json()["access_token"]

    resp = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@patch("tenderai_bf.api.routers.users.send_credentials_email", return_value=True)
def test_create_user_sends_email(mock_email, client, admin_token):
    resp = client.post(
        "/api/v1/users",
        json={"username": "newuser", "email": "new@test.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == "newuser"
    assert mock_email.called


def test_deactivate_user(client, admin_token, db_session):
    user = User(
        id=str(uuid.uuid4()),
        username="todeactivate",
        email="deact@test.com",
        hashed_password=get_password_hash("pass123"),
        role="viewer",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(user)
    db_session.commit()

    resp = client.patch(
        f"/api/v1/users/{user.id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_admin_cannot_deactivate_self(client, admin_token, db_session):
    admin = db_session.query(User).filter_by(username="admin").first()
    resp = client.patch(
        f"/api/v1/users/{admin.id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
