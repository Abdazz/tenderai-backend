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


def test_get_section_returns_none_when_absent(db):
    from tenderai_bf.settings_store import SettingsStore
    assert SettingsStore.get_section(db, "pipeline") is None


def test_put_section_inserts_new_row(db):
    from tenderai_bf.settings_store import SettingsStore
    SettingsStore.put_section(db, "pipeline", {"min_relevance_score": 0.8}, updated_by="admin")
    result = SettingsStore.get_section(db, "pipeline")
    assert result == {"min_relevance_score": 0.8}


def test_put_section_updates_existing_row(db):
    from tenderai_bf.settings_store import SettingsStore
    SettingsStore.put_section(db, "pipeline", {"min_relevance_score": 0.7}, updated_by="admin")
    SettingsStore.put_section(db, "pipeline", {"min_relevance_score": 0.9}, updated_by="admin")
    result = SettingsStore.get_section(db, "pipeline")
    assert result["min_relevance_score"] == 0.9


def test_get_all_returns_all_sections(db):
    from tenderai_bf.settings_store import SettingsStore
    SettingsStore.put_section(db, "pipeline", {"x": 1}, updated_by="admin")
    SettingsStore.put_section(db, "llm", {"provider": "groq"}, updated_by="admin")
    result = SettingsStore.get_all(db)
    assert "pipeline" in result
    assert "llm" in result
    assert result["pipeline"]["x"] == 1


def test_seed_from_settings_inserts_all_sections(db):
    from tenderai_bf.settings_store import SettingsStore
    seeded = SettingsStore.seed_from_settings(db)
    assert len(seeded) == 7
    assert "pipeline" in seeded
    assert "scheduler" in seeded
    assert "llm" in seeded
    assert "email" in seeded
    assert "rag" in seeded
    assert "classification" in seeded
    assert "prompts" in seeded


def test_seed_from_settings_is_idempotent(db):
    from tenderai_bf.settings_store import SettingsStore
    seeded_first = SettingsStore.seed_from_settings(db)
    seeded_second = SettingsStore.seed_from_settings(db)
    assert len(seeded_first) == 7
    assert len(seeded_second) == 0  # nothing inserted on second call


def test_reload_settings_from_db_applies_overrides(db):
    from tenderai_bf.settings_store import SettingsStore
    from tenderai_bf.config import settings, reload_settings_from_db

    original = settings.processing.min_relevance_score
    new_score = round(original + 0.1, 2) if original < 0.9 else 0.5

    SettingsStore.put_section(
        db, "pipeline",
        {
            "max_items_per_run": 100,
            "min_relevance_score": new_score,
            "deduplication_threshold": 0.75,
            "deduplication_method": "hash_similarity",
            "use_llm_classification": True,
            "pdf_timeout": 120,
            "max_file_size_mb": 50,
        },
        updated_by="test",
    )
    reload_settings_from_db(db)
    assert settings.processing.min_relevance_score == new_score
