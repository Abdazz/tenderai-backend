import os
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.db import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_country_table_has_expected_columns(db):
    from tenderai_bf.models import Country
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("countries")}
    assert {"id", "name", "code", "locale", "active", "created_at", "updated_at"}.issubset(cols)


def test_country_settings_table_has_expected_columns(db):
    from tenderai_bf.models import CountrySettings
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("country_settings")}
    assert {"country_id", "section", "data", "updated_at", "updated_by"}.issubset(cols)


def test_source_has_country_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("sources")}
    assert "country_id" in cols


def test_run_has_country_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("runs")}
    assert "country_id" in cols


def test_recipient_has_country_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("recipients")}
    assert "country_id" in cols
