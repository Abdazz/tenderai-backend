# src/tenderai_bf/api/schemas/settings.py
"""Pydantic validation schemas for settings sections."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

DEDUP_METHODS = {"hash_only", "similarity_only", "hash_similarity", "llm_only", "hybrid"}
LLM_PROVIDERS = {"groq", "openai", "ollama"}


class PipelineSettingsSchema(BaseModel):
    max_items_per_run: int = Field(ge=1, le=10000)
    min_relevance_score: float = Field(ge=0.0, le=1.0)
    deduplication_threshold: float = Field(ge=0.0, le=1.0)
    deduplication_method: str
    use_llm_classification: bool
    pdf_timeout: int = Field(ge=10)
    max_file_size_mb: int = Field(ge=1)

    def model_post_init(self, __context: Any) -> None:
        if self.deduplication_method not in DEDUP_METHODS:
            raise ValueError(
                f"deduplication_method must be one of {DEDUP_METHODS}"
            )


class SchedulerSettingsSchema(BaseModel):
    cron_schedule: str
    timezone: str
    enabled: bool
    max_concurrent_runs: int = Field(ge=1)
    run_on_startup: bool

    def model_post_init(self, __context: Any) -> None:
        parts = self.cron_schedule.strip().split()
        if len(parts) != 5:
            raise ValueError("cron_schedule must have exactly 5 fields (min hr dom mon dow)")


class LLMSettingsSchema(BaseModel):
    provider: str
    groq_model: str
    openai_model: str
    ollama_model: str
    ollama_base_url: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=100)
    timeout: int = Field(ge=10)

    def model_post_init(self, __context: Any) -> None:
        if self.provider not in LLM_PROVIDERS:
            raise ValueError(f"provider must be one of {LLM_PROVIDERS}")


class EmailSettingsSchema(BaseModel):
    from_address: str
    from_name: str
    to_address: str
    reply_to: Optional[str] = None
    subject_prefix: str
    signature: str


class RAGSettingsSchema(BaseModel):
    enabled: bool
    chunk_size: int = Field(ge=64)
    chunk_overlap: int = Field(ge=0)
    top_k_results: int = Field(ge=1, le=100)
    embedding_model: str
    vector_search_query: str


class PromptPair(BaseModel):
    system: str
    user_template: str


class PromptsSettingsSchema(BaseModel):
    extraction: PromptPair
    classification: PromptPair
    summarization: PromptPair
    deduplication: PromptPair


class ClassificationSettingsSchema(BaseModel):
    relevant_keywords: Dict[str, List[str]]


SECTION_SCHEMAS: Dict[str, type] = {
    "pipeline": PipelineSettingsSchema,
    "scheduler": SchedulerSettingsSchema,
    "llm": LLMSettingsSchema,
    "email": EmailSettingsSchema,
    "rag": RAGSettingsSchema,
    "classification": ClassificationSettingsSchema,
    "prompts": PromptsSettingsSchema,
}
