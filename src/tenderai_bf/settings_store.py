# src/tenderai_bf/settings_store.py
"""DB-backed settings store. One row per section in app_settings."""

from typing import Optional
from sqlalchemy.orm import Session

from .models import AppSettings

MUTABLE_SECTIONS = frozenset(
    {"pipeline", "scheduler", "llm", "email", "rag", "classification", "prompts"}
)


class SettingsStore:

    @staticmethod
    def get_section(db: Session, section: str) -> Optional[dict]:
        row = db.query(AppSettings).filter(AppSettings.section == section).first()
        return row.data if row else None

    @staticmethod
    def put_section(
        db: Session, section: str, data: dict, updated_by: str = "system"
    ) -> None:
        row = db.query(AppSettings).filter(AppSettings.section == section).first()
        if row:
            row.data = data
            row.updated_by = updated_by
        else:
            db.add(AppSettings(section=section, data=data, updated_by=updated_by))
        db.commit()

    @staticmethod
    def get_all(db: Session) -> dict[str, dict]:
        rows = db.query(AppSettings).all()
        return {row.section: row.data for row in rows}

    @staticmethod
    def seed_from_settings(db: Session) -> list[str]:
        """Seed DB from the current in-memory Settings singleton.

        Inserts only sections that don't yet exist. Idempotent.
        Returns list of section names that were inserted.
        """
        from .config import settings as s

        sections_data: dict[str, dict] = {
            "pipeline": {
                "max_items_per_run": s.processing.max_items_per_run,
                "min_relevance_score": s.processing.min_relevance_score,
                "deduplication_threshold": s.processing.deduplication_threshold,
                "deduplication_method": s.processing.deduplication_method,
                "use_llm_classification": s.processing.use_llm_classification,
                "pdf_timeout": s.processing.pdf_timeout,
                "max_file_size_mb": s.processing.max_file_size_mb,
            },
            "scheduler": {
                "cron_schedule": s.scheduler.cron_schedule,
                "timezone": s.scheduler.timezone,
                "enabled": s.scheduler.enabled,
                "max_concurrent_runs": s.scheduler.max_concurrent_runs,
                "run_on_startup": s.scheduler.run_on_startup,
            },
            "llm": {
                "provider": s.llm.provider,
                "groq_model": s.llm.groq_model,
                "openai_model": s.llm.openai_model,
                "ollama_model": s.llm.ollama_model,
                "ollama_base_url": s.llm.ollama_base_url,
                "temperature": s.llm.temperature,
                "max_tokens": s.llm.max_tokens,
                "timeout": s.llm.timeout,
            },
            "email": {
                "from_address": s.email.from_address,
                "from_name": s.email.from_name,
                "to_address": s.email.to_address,
                "reply_to": s.email.reply_to,
                "subject_prefix": s.email.subject_prefix,
                "signature": s.email.signature,
            },
            "rag": {
                "enabled": s.rag.enabled,
                "chunk_size": s.rag.chunk_size,
                "chunk_overlap": s.rag.chunk_overlap,
                "top_k_results": s.rag.top_k_results,
                "embedding_model": s.rag.embedding_model,
                "vector_search_query": s.rag.chroma.vector_search_query,
            },
            "classification": {
                "relevant_keywords": s.classification.relevant_keywords,
            },
            "prompts": s.prompts,
        }

        seeded: list[str] = []
        for section, data in sections_data.items():
            exists = (
                db.query(AppSettings)
                .filter(AppSettings.section == section)
                .first()
            )
            if exists:
                continue
            db.add(AppSettings(section=section, data=data, updated_by="seed"))
            seeded.append(section)
        db.commit()
        return seeded
