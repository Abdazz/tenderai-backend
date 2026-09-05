import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai.db import Base  # noqa: E402 — must follow env var setup above


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_country_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("countries")}
    assert {
        "id",
        "name",
        "code",
        "locale",
        "active",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_country_settings_table_has_expected_columns(db):
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


def test_country_store_get_section_returns_none_when_absent(db):
    from tenderai.country_store import CountryStore
    from tenderai.models import Country

    country = Country(name="Test", code="XX", locale="fr")
    db.add(country)
    db.commit()
    assert CountryStore.get_section(db, country.id, "pipeline") is None


def test_country_store_put_and_get_section(db):
    from tenderai.country_store import CountryStore
    from tenderai.models import Country

    country = Country(name="Test", code="TT", locale="fr")
    db.add(country)
    db.commit()
    CountryStore.put_section(
        db, country.id, "pipeline", {"min_relevance_score": 0.6}, updated_by="test"
    )
    result = CountryStore.get_section(db, country.id, "pipeline")
    assert result == {"min_relevance_score": 0.6}


def test_country_store_get_all_with_fallback_uses_global_for_missing(db):
    from tenderai.country_store import CountryStore
    from tenderai.models import AppSettings, Country

    # Insert global setting
    db.add(
        AppSettings(
            section="email",
            data={"to_address": "global@example.com"},
            updated_by="test",
        )
    )
    db.commit()
    # Country with no country-specific email setting
    country = Country(name="New", code="NW", locale="fr")
    db.add(country)
    db.commit()
    result = CountryStore.get_all_with_fallback(db, country.id)
    assert result["email"]["to_address"] == "global@example.com"


def test_country_store_get_all_with_fallback_country_overrides_global(db):
    from tenderai.country_store import CountryStore
    from tenderai.models import AppSettings, Country

    db.add(
        AppSettings(
            section="email",
            data={"to_address": "global@example.com"},
            updated_by="test",
        )
    )
    db.commit()
    country = Country(name="Override", code="OV", locale="fr")
    db.add(country)
    db.commit()
    CountryStore.put_section(
        db,
        country.id,
        "email",
        {"to_address": "country@example.com"},
        updated_by="test",
    )
    result = CountryStore.get_all_with_fallback(db, country.id)
    assert result["email"]["to_address"] == "country@example.com"


def test_country_store_seed_from_global_copies_all_sections(db):
    from tenderai.country_store import CountryStore
    from tenderai.models import AppSettings, Country

    db.add(AppSettings(section="pipeline", data={"pdf_timeout": 30}, updated_by="test"))
    db.add(AppSettings(section="llm", data={"provider": "groq"}, updated_by="test"))
    db.commit()
    country = Country(name="Seed", code="SD", locale="fr")
    db.add(country)
    db.commit()
    seeded = CountryStore.seed_from_global(db, country.id)
    assert set(seeded) == {"pipeline", "llm"}
    assert CountryStore.get_section(db, country.id, "pipeline") == {"pdf_timeout": 30}
