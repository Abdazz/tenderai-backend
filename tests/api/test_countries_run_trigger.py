import os
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

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
from tenderai_bf.models import Base, Company, Country, User  # noqa: E402


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


@patch("tenderai_bf.db.get_db_context")
@patch("tenderai_bf.agents.get_delivery_pipeline")
@patch("tenderai_bf.agents.get_pipeline")
def test_trigger_run_calls_both_harvest_and_delivery(
    mock_get_pipeline,
    mock_get_delivery_pipeline,
    mock_get_db_context,
    client,
    admin_token,
    db_session,
):
    country = Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True)
    company = Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True)
    db_session.add_all([country, company])
    db_session.commit()

    # countries.py's background _run() does `from ...db import get_db_context`
    # freshly on every call and looks up the YULCOM company through it — a
    # completely separate connection from this test's own in-memory
    # db_session/FastAPI override unless patched to yield the same session.
    @contextmanager
    def _shared_db_context():
        yield db_session

    mock_get_db_context.side_effect = _shared_db_context

    mock_harvest_pipeline = MagicMock()
    mock_harvest_pipeline.run.return_value = MagicMock(error_occurred=False)
    mock_get_pipeline.return_value = mock_harvest_pipeline

    mock_delivery_pipeline = MagicMock()
    mock_get_delivery_pipeline.return_value = mock_delivery_pipeline

    resp = client.post(
        "/api/v1/admin/countries/1/run",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 202

    assert mock_harvest_pipeline.run.called
    assert mock_delivery_pipeline.run.called
    delivery_kwargs = mock_delivery_pipeline.run.call_args.kwargs
    assert delivery_kwargs["company_id"] == 1
    assert delivery_kwargs["country_id"] == 1
