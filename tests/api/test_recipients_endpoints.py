import os
import uuid

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from tenderai_bf.api.dependencies import get_password_hash  # noqa: E402
from tenderai_bf.api.main import app  # noqa: E402
from tenderai_bf.db import get_db  # noqa: E402
from tenderai_bf.models import Base, Company, Recipient, User  # noqa: E402


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


@pytest.fixture
def admin_token(client, db_session):
    admin = User(
        id=str(uuid.uuid4()),
        username="admin",
        email="admin@test.com",
        hashed_password=get_password_hash("adminpass123"),
        role="super_admin",
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


def test_create_recipient_defaults_to_yulcom_company(client, admin_token, db_session):
    """A recipient created via the API (no company selection UI yet) must be
    attached to YULCOM, not left with company_id=NULL — otherwise it's
    silently excluded from email_report_node's company-scoped query."""
    yulcom = Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True)
    db_session.add(yulcom)
    db_session.commit()

    resp = client.post(
        "/api/v1/recipients",
        json={"email": "new-recipient@example.com", "name": "New Recipient"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new-recipient@example.com"

    row = (
        db_session.query(Recipient)
        .filter(Recipient.email == "new-recipient@example.com")
        .first()
    )
    assert row is not None
    assert row.company_id == yulcom.id
