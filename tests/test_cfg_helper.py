"""Tests for the cfg() state config accessor."""
import os

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import pytest  # noqa: E402 — must follow env var setup above

from tenderai_bf.agents.graph import (  # noqa: E402 — must follow env var setup above
    TenderAIState,
    cfg,
)


def make_state(**country_config_override):
    return TenderAIState(
        country_id=1,
        country_config={
            "pipeline": {
                "use_llm_classification": False,
                "min_relevance_score": 0.5,
                "deduplication_method": "hash_only",
                "deduplication_threshold": 0.85,
                "max_items_per_run": 100,
                "pdf_timeout": 30,
                "max_file_size_mb": 10,
            },
            "llm": {
                "provider": "groq",
                "groq_model": "llama-3.3-70b-versatile",
                "openai_model": "gpt-4o",
                "ollama_model": "llama3",
                "ollama_base_url": "",
                "temperature": 0.1,
                "max_tokens": 2000,
                "timeout": 60,
            },
            **country_config_override,
        },
    )


def test_cfg_returns_existing_value():
    state = make_state()
    assert cfg(state, "pipeline", "max_items_per_run") == 100


def test_cfg_missing_section_raises():
    state = make_state()
    with pytest.raises(RuntimeError, match="Missing DB config"):
        cfg(state, "nonexistent_section", "some_key")


def test_cfg_missing_key_raises():
    state = make_state()
    with pytest.raises(RuntimeError, match="Missing DB config"):
        cfg(state, "pipeline", "nonexistent_key")


def test_cfg_error_message_includes_country_id_section_key():
    state = make_state()
    state.country_id = 42
    with pytest.raises(RuntimeError) as exc_info:
        cfg(state, "missing_section", "missing_key")
    msg = str(exc_info.value)
    assert "42" in msg
    assert "missing_section" in msg
    assert "missing_key" in msg


def test_company_cfg_reads_company_config():
    from typing import ClassVar

    from tenderai_bf.agents._cfg import company_cfg

    class FakeState:
        company_id = 5
        company_config: ClassVar = {"classification": {"min_relevance_score": 0.4}}

    assert company_cfg(FakeState(), "classification", "min_relevance_score") == 0.4


def test_company_cfg_fails_hard_if_missing():
    from typing import ClassVar

    import pytest

    from tenderai_bf.agents._cfg import company_cfg

    class FakeState:
        company_id = 5
        company_config: ClassVar = {}

    with pytest.raises(RuntimeError, match="Missing DB config: company_id=5"):
        company_cfg(FakeState(), "classification", "min_relevance_score")
