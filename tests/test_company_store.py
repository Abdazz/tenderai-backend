import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.db import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_company_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("companies")}
    assert {
        "id",
        "name",
        "slug",
        "active",
        "logo_url",
        "subject_prefix",
        "signature",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_company_country_subscription_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_country_subscriptions")}
    assert {"company_id", "country_id", "enabled", "created_at"}.issubset(cols)
