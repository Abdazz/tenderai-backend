"""Configuration management using Pydantic Settings."""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in strings.

    Supports syntax: ${VAR_NAME:-default_value} or ${VAR_NAME}
    """
    if isinstance(value, str):
        # Match ${VAR_NAME:-default} or ${VAR_NAME}
        def replacer(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default = var_expr.split(":-", 1)
                return os.environ.get(var_name, default)
            else:
                return os.environ.get(var_expr, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replacer, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DATABASE_", case_sensitive=False)

    url: str = Field(
        default="postgresql://tenderai:tenderai_pass@localhost:5432/tenderai_bf",
        description="Full database connection URL",
    )
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="tenderai_bf")
    user: str = Field(default="tenderai")
    password: SecretStr = Field(default="tenderai_pass")

    echo: bool = Field(default=False, description="Enable SQL query logging")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max pool overflow")


class MinIOSettings(BaseSettings):
    """MinIO S3-compatible storage configuration."""

    model_config = SettingsConfigDict(env_prefix="MINIO_", case_sensitive=False)

    endpoint: str = Field(default="localhost:9000")
    access_key: str = Field(default="minioadmin")
    secret_key: SecretStr = Field(default="minioadmin123")
    bucket_name: str = Field(default="tenderai-bf")
    secure: bool = Field(default=False)
    region: str = Field(default="us-east-1", description="S3 region")


class SMTPSettings(BaseSettings):
    """SMTP email configuration."""

    host: str = Field(default="smtp.gmail.com")
    port: int = Field(default=587)
    user: str = Field(default="")
    password: SecretStr = Field(default="")
    use_tls: bool = Field(default=True)
    use_ssl: bool = Field(default=False)
    timeout: int = Field(default=30, description="SMTP timeout in seconds")

    model_config = SettingsConfigDict(env_prefix="SMTP_", case_sensitive=False)


class EmailSettings(BaseSettings):
    """Email template and recipient configuration."""

    from_address: str = Field(default="noreply@yulcom.com")
    from_name: str = Field(default="TenderAI BF")
    to_address: str = Field(default="tender-watch@yulcom.com")
    reply_to: str | None = Field(default="support@yulcom.com")
    subject_prefix: str = Field(default="RFP Watch – Burkina Faso")  # noqa: RUF001 — intentional em dash in display text
    signature: str = Field(default="YULCOM Technologies")
    logo_url: str | None = Field(default=None, validation_alias="EMAIL_LOGO_URL")

    model_config = SettingsConfigDict(env_prefix="EMAIL_", case_sensitive=False)


class LLMSettings(BaseSettings):
    """Large Language Model configuration."""

    provider: str = Field(default="groq", validation_alias="LLM_PROVIDER")
    groq_api_key: SecretStr = Field(default="", validation_alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL"
    )
    openai_api_key: SecretStr = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(
        default="gpt-4-turbo-preview", validation_alias="OPENAI_MODEL"
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3.1", validation_alias="OLLAMA_MODEL")
    nvidia_api_key: SecretStr = Field(default="", validation_alias="NVIDIA_API_KEY")
    nvidia_model: str = Field(
        default="meta/llama-3.3-70b-instruct", validation_alias="NVIDIA_MODEL"
    )
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        validation_alias="NVIDIA_BASE_URL",
    )
    temperature: float = Field(default=0.1, description="LLM temperature")
    max_tokens: int = Field(default=2048, description="Max response tokens")
    timeout: int = Field(default=60, description="LLM request timeout")

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


class OCRSettings(BaseSettings):
    """OCR configuration."""

    enabled: bool = Field(default=True)
    language: str = Field(default="fra")
    timeout: int = Field(default=300)
    tesseract_path: str = Field(default="/usr/bin/tesseract")
    confidence_threshold: float = Field(
        default=0.5, description="Minimum OCR confidence"
    )

    model_config = SettingsConfigDict(env_prefix="OCR_", case_sensitive=False)


class SchedulerSettings(BaseSettings):
    """Scheduler configuration."""

    cron_schedule: str = Field(default="0 7 * * *")
    enabled: bool = Field(default=True)
    timezone: str = Field(default="Africa/Ouagadougou")
    max_concurrent_runs: int = Field(
        default=1, description="Max concurrent pipeline runs"
    )
    run_on_startup: bool = Field(default=False, description="Run pipeline on startup")

    model_config = SettingsConfigDict(case_sensitive=False)


class SecuritySettings(BaseSettings):
    """Security configuration."""

    secret_key: SecretStr = Field(default="")
    admin_password: SecretStr = Field(
        default="",
        validation_alias="TENDERAI_ADMIN_PASSWORD",
    )
    admin_username: str = Field(
        default="admin",
        validation_alias="TENDERAI_ADMIN_USERNAME",
    )
    session_timeout: int = Field(default=3600, description="Session timeout in seconds")

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


class MonitoringSettings(BaseSettings):
    """Monitoring and observability configuration."""

    metrics_enabled: bool = Field(default=True)
    metrics_port: int = Field(default=9090)
    health_check_timeout: int = Field(default=30)
    # Logging
    log_level: str = "INFO"

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="",
        validation_alias="TENDERAI_JWT_SECRET",
        description="Secret key for JWT token signing — must be set via TENDERAI_JWT_SECRET env var",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


class ProcessingSettings(BaseSettings):
    """Processing limits and thresholds."""

    default_rate_limit: int = Field(default=10)
    min_relevance_score: float = Field(default=0.7)
    use_llm_classification: bool = Field(
        default=True, description="Use LLM for classification instead of keywords"
    )
    max_items_per_run: int = Field(default=100)
    deduplication_threshold: float = Field(default=0.85)
    deduplication_method: str = Field(
        default="hash_similarity",
        description="Deduplication method: 'hash_only', 'similarity_only', 'hash_similarity', 'llm_only', 'hybrid'",
    )
    pdf_timeout: int = Field(default=120)
    max_file_size_mb: int = Field(default=50)

    model_config = SettingsConfigDict(case_sensitive=False)


class ClassificationSettings(BaseSettings):
    """Classification configuration."""

    relevant_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "it_services": [
                "informatique",
                "logiciel",
                "développement",
                "application",
                "système d'information",
                "base de données",
                "réseau",
                "cybersécurité",
                "cloud",
                "numérique",
                "digital",
                "site web",
                "plateforme",
                "e-gouvernement",
                "gestion électronique",
            ],
            "engineering": [
                "ingénierie",
                "génie civil",
                "infrastructure",
                "construction",
                "BTP",
                "routes",
                "bâtiment",
                "électricité",
                "télécommunications",
                "énergie",
                "hydraulique",
                "assainissement",
            ],
            "consulting": [
                "conseil",
                "consultance",
                "étude",
                "expertise",
                "assistance technique",
                "formation",
                "audit",
                "évaluation",
            ],
            "it_hardware": [
                "équipement informatique",
                "matériel informatique",
                "ordinateur",
                "serveur",
                "poste de travail",
                "matériel de bureau",
                "imprimante",
                "scanner",
                "photocopieur",
                "disque dur",
                "mémoire RAM",
                "processeur",
                "carte graphique",
                "carte mère",
                "alimentation électrique",
                "onduleur",
                "batterie",
                "câbles",
                "connecteurs",
                "accessoires informatiques",
                "écran",
                "moniteur",
                "clavier",
                "souris",
                "hub USB",
                "adaptateur",
                "routeur",
                "switch réseau",
                "modem",
                "point d'accès wifi",
                "disque SSD",
                "lecteur optique",
                "webcam",
                "microphone",
                "enceinte",
                "casque audio",
            ],
        },
        description="Keywords grouped by category for relevance classification",
    )

    model_config = SettingsConfigDict(case_sensitive=False)


class FetchSettings(BaseSettings):
    """HTTP fetching configuration."""

    user_agent: str = Field(
        default="TenderAI-BF/1.0", description="User-Agent header for HTTP requests"
    )
    timeout: int = Field(default=30, description="Default HTTP timeout in seconds")
    follow_redirects: bool = Field(default=True)
    max_retries: int = Field(default=3)

    model_config = SettingsConfigDict(env_prefix="FETCH_", case_sensitive=False)


class RAGChromaSettings(BaseSettings):
    """Chroma vector database settings for RAG."""

    persist_directory: str = Field(default="/app/data/chroma_db")
    collection_prefix: str = Field(default="tenders")
    host: str | None = Field(default=None)
    port: int | None = Field(default=None)
    track_metadata: list[str] = Field(
        default_factory=lambda: [
            "source",
            "date",
            "filename",
            "page_number",
            "tender_id",
        ]
    )
    vector_search_query: str = Field(
        default="Extraire les appels d'offres publics, entités, dates limites, et pertinence IT/Ingénierie",
        description="Query for vector similarity search (should match document language)",
    )
    llm_query_template: str = Field(
        default="Extract all tenders from the following documents"
    )

    model_config = SettingsConfigDict(case_sensitive=False)


class GoogleSearchSettings(BaseSettings):
    """Google Custom Search API configuration."""

    api_key: SecretStr = Field(default="", validation_alias="GOOGLE_API_KEY")
    engine_id: str = Field(default="", validation_alias="GOOGLE_SEARCH_ENGINE_ID")
    max_results_per_query: int = Field(default=10)

    model_config = SettingsConfigDict(case_sensitive=False)


class TavilySettings(BaseSettings):
    """Tavily web search/extract API configuration."""

    api_key: SecretStr = Field(default="", validation_alias="TAVILY_API_KEY")
    max_results: int = Field(default=10)
    search_depth: str = Field(default="basic")  # "basic" | "advanced"

    model_config = SettingsConfigDict(case_sensitive=False)


class RAGSettings(BaseSettings):
    """RAG (Retrieval-Augmented Generation) configuration."""

    enabled: bool = Field(default=True)
    vector_db: str = Field(default="chroma")
    embedding_model: str = Field(default="all-MiniLM-L6-v2")
    chunk_size: int = Field(default=512)
    chunk_overlap: int = Field(default=50)
    top_k_results: int = Field(default=5)
    chroma: RAGChromaSettings = Field(default_factory=RAGChromaSettings)

    model_config = SettingsConfigDict(env_prefix="RAG_", case_sensitive=False)


class Settings(BaseSettings):
    """Main application settings."""

    app_name: str = Field(default="TenderAI")
    app_version: str = Field(default="0.1.0")
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    minio: MinIOSettings = Field(default_factory=MinIOSettings)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    classification: ClassificationSettings = Field(
        default_factory=ClassificationSettings
    )
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    google_search: GoogleSearchSettings = Field(default_factory=GoogleSearchSettings)
    tavily: TavilySettings = Field(default_factory=TavilySettings)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    def __init__(self, **kwargs):
        """Initialize settings and load external configuration."""
        super().__init__(**kwargs)
        self._load_yaml_config()
        self._validate_security()

    def _load_yaml_config(self) -> None:
        """Load infra-only overrides from settings.yaml.

        Operational config (llm, pipeline, classification, prompts, rag,
        scheduler, email) is seeded into the DB at startup and read from
        country_settings at runtime — not from this file.
        """
        yaml_path = Path("settings.yaml")
        if not yaml_path.exists():
            return
        try:
            with open(yaml_path, encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f)
            if not yaml_config:
                return
            yaml_config = expand_env_vars(yaml_config)
            if "ocr" in yaml_config:
                ocr_config = yaml_config["ocr"]
                if "enabled" in ocr_config:
                    self.ocr.enabled = ocr_config["enabled"]
                if "language" in ocr_config:
                    self.ocr.language = ocr_config["language"]
        except Exception as e:
            print(f"Warning: Could not load settings.yaml: {e}")

    def _validate_security(self) -> None:
        """Refuse to boot if security credentials are missing or trivially weak.

        No fallbacks are accepted in any environment: the JWT secret and admin
        password must be set via TENDERAI_JWT_SECRET / TENDERAI_ADMIN_PASSWORD.
        """
        # Trivial/known-bad values that must never be accepted, even outside production.
        TRIVIAL_PASSWORDS = {  # noqa: N806 — module-level-style constant, scoped locally by design
            "admin",
            "admin123",
            "password",
            "changeme",
            "test",
            "tenderai",
            "12345",
            "123456",
            "qwerty",
        }
        TRIVIAL_JWT_SECRETS = {  # noqa: N806 — module-level-style constant, scoped locally by design
            "change-this-secret-key-in-production-use-openssl-rand-hex-32",
            "secret",
            "changeme",
            "test",
        }

        issues = []

        admin_pwd = self.security.admin_password.get_secret_value()
        if not admin_pwd:
            issues.append(
                "TENDERAI_ADMIN_PASSWORD is not set — configure it via the "
                "TENDERAI_ADMIN_PASSWORD env var"
            )
        elif admin_pwd.lower() in TRIVIAL_PASSWORDS or len(admin_pwd) < 8:
            issues.append(
                "TENDERAI_ADMIN_PASSWORD is too weak — use at least 8 characters "
                "and avoid common defaults"
            )

        jwt_key = self.monitoring.jwt_secret_key
        if not jwt_key:
            issues.append(
                "TENDERAI_JWT_SECRET is not set — generate one with "
                "`openssl rand -hex 32` and export it as TENDERAI_JWT_SECRET"
            )
        elif jwt_key in TRIVIAL_JWT_SECRETS or len(jwt_key) < 32:
            issues.append(
                "TENDERAI_JWT_SECRET is too weak — use at least 32 characters "
                "(e.g. `openssl rand -hex 32`)"
            )

        if issues:
            raise ValueError(
                "Security misconfiguration:\n" + "\n".join(f"  - {i}" for i in issues)
            )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment setting."""
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"Environment must be one of: {allowed}")
        return v

    @field_validator("llm")
    @classmethod
    def validate_llm_provider(cls, v):
        """Validate LLM provider configuration."""
        if v.provider == "groq" and not v.groq_api_key.get_secret_value():
            print("Warning: Groq API key not set")
        elif v.provider == "openai" and not v.openai_api_key.get_secret_value():
            print("Warning: OpenAI API key not set")
        elif v.provider == "nvidia" and not v.nvidia_api_key.get_secret_value():
            print("Warning: NVIDIA API key not set")
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "development"

    def get_database_url(self) -> str:
        """Get the complete database URL."""
        return self.database.url


# Global settings instance
settings = Settings()
