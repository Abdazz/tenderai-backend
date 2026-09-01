import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai.db import Base  # noqa: E402 — must follow the env var setup above


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_company_store_get_section_returns_none_when_absent(db):
    from tenderai.company_store import CompanyStore
    from tenderai.models import Company

    company = Company(name="Test", slug="test-co")
    db.add(company)
    db.commit()
    assert CompanyStore.get_section(db, company.id, "classification") is None


def test_company_store_put_and_get_section(db):
    from tenderai.company_store import CompanyStore
    from tenderai.models import Company

    company = Company(name="Test", slug="test-co2")
    db.add(company)
    db.commit()
    CompanyStore.put_section(
        db,
        company.id,
        "classification",
        {"min_relevance_score": 0.6},
        updated_by="test",
    )
    result = CompanyStore.get_section(db, company.id, "classification")
    assert result == {"min_relevance_score": 0.6}


def test_company_store_get_all_with_fallback_uses_global_for_missing(db):
    from tenderai.company_store import CompanyStore
    from tenderai.models import AppSettings, Company

    db.add(
        AppSettings(
            section="email",
            data={"subject_prefix": "TenderAI"},
            updated_by="test",
        )
    )
    db.commit()
    company = Company(name="New", slug="new-co")
    db.add(company)
    db.commit()
    result = CompanyStore.get_all_with_fallback(db, company.id)
    assert result["email"]["subject_prefix"] == "TenderAI"


def test_company_store_get_all_with_fallback_company_overrides_global(db):
    from tenderai.company_store import CompanyStore
    from tenderai.models import AppSettings, Company

    db.add(
        AppSettings(
            section="email",
            data={"subject_prefix": "TenderAI"},
            updated_by="test",
        )
    )
    db.commit()
    company = Company(name="Override", slug="override-co")
    db.add(company)
    db.commit()
    CompanyStore.put_section(
        db,
        company.id,
        "email",
        {"subject_prefix": "[ACME]"},
        updated_by="test",
    )
    result = CompanyStore.get_all_with_fallback(db, company.id)
    assert result["email"]["subject_prefix"] == "[ACME]"


def test_company_store_seed_from_global_copies_all_sections(db):
    from tenderai.company_store import CompanyStore
    from tenderai.models import AppSettings, Company

    db.add(
        AppSettings(
            section="classification",
            data={"min_relevance_score": 0.65},
            updated_by="test",
        )
    )
    db.add(
        AppSettings(
            section="scheduler", data={"cron_schedule": "0 7 * * *"}, updated_by="test"
        )
    )
    db.commit()
    company = Company(name="Seed", slug="seed-co")
    db.add(company)
    db.commit()
    seeded = CompanyStore.seed_from_global(db, company.id)
    assert set(seeded) == {"classification", "scheduler"}
    assert CompanyStore.get_section(db, company.id, "classification") == {
        "min_relevance_score": 0.65
    }
