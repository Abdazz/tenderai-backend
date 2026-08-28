import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.db import Base  # noqa: E402 — must follow the env var setup above


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


def test_company_settings_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_settings")}
    assert {"company_id", "section", "data", "updated_at", "updated_by"}.issubset(cols)


def test_sqlalchemy_mapper_registry_configures_cleanly(db):
    """Guards against the Task 1 regression: a relationship() referencing a
    not-yet-existing class breaks configure_mappers() for the whole process,
    not just the model that declares it."""
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


def test_company_notice_status_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_notice_status")}
    assert {
        "id",
        "company_id",
        "notice_id",
        "is_relevant",
        "relevance_score",
        "classification_method",
        "delivered_at",
        "created_at",
    }.issubset(cols)


def test_company_notice_status_unique_per_company_and_notice(db):
    import uuid

    from tenderai_bf.models import Company, CompanyNoticeStatus, Notice, Run, Source

    company = Company(name="Test Co", slug="test-co")
    db.add(company)
    source = Source(
        name="src", base_url="https://x", list_url="https://x/list", parser_type="html"
    )
    db.add(source)
    run = Run(id=str(uuid.uuid4()), status="completed", triggered_by="manual")
    db.add(run)
    db.commit()

    notice = Notice(
        id=str(uuid.uuid4()),
        source_id=source.id,
        run_id=run.id,
        title="Test notice",
        content_hash="a" * 64,
        url="https://x/notice/1",
    )
    db.add(notice)
    db.commit()

    status = CompanyNoticeStatus(
        id=str(uuid.uuid4()),
        company_id=company.id,
        notice_id=notice.id,
        is_relevant=True,
        relevance_score=0.9,
    )
    db.add(status)
    db.commit()

    dupe = CompanyNoticeStatus(
        id=str(uuid.uuid4()),
        company_id=company.id,
        notice_id=notice.id,
        is_relevant=False,
    )
    db.add(dupe)
    with pytest.raises(IntegrityError):
        db.commit()


def test_run_has_run_type_and_company_id_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("runs")}
    assert {"run_type", "company_id"}.issubset(cols)


def test_recipient_has_company_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("recipients")}
    assert "company_id" in cols


def test_user_has_company_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert "company_id" in cols
