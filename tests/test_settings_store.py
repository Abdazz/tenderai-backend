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


def test_app_settings_table_has_expected_columns(db):
    from tenderai_bf.models import AppSettings
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("app_settings")}
    assert cols == {"section", "data", "updated_at", "updated_by"}


def test_app_settings_can_insert_and_retrieve(db):
    from tenderai_bf.models import AppSettings
    row = AppSettings(section="pipeline", data={"min_relevance_score": 0.7}, updated_by="test")
    db.add(row)
    db.commit()
    found = db.query(AppSettings).filter_by(section="pipeline").first()
    assert found is not None
    assert found.data["min_relevance_score"] == 0.7
