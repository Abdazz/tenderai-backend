"""Configuration management using Pydantic Settings."""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic.types import SecretStr


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in strings.
    
    Supports syntax: ${VAR_NAME:-default_value} or ${VAR_NAME}
    """
    if isinstance(value, str):
        # Match ${VAR_NAME:-default} or ${VAR_NAME}
        def replacer(match):
            var_expr = match.group(1)
            if ':-' in var_expr:
                var_name, default = var_expr.split(':-', 1)
                return os.environ.get(var_name, default)
            else:
                return os.environ.get(var_expr, match.group(0))
        
        return re.sub(r'\$\{([^}]+)\}', replacer, value)
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


class DatabaseSettings(BaseSettings):
    """Database configuration."""
    
    model_config = SettingsConfigDict(env_prefix='DATABASE_', case_sensitive=False)
    
    url: str = Field(
        default="postgresql://tenderai:tenderai_pass@localhost:5432/tenderai_bf",
        description="Full database connection URL"
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
    
    model_config = SettingsConfigDict(env_prefix='MINIO_', case_sensitive=False)
    
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
    
    model_config = SettingsConfigDict(env_prefix='SMTP_', case_sensitive=False)


class EmailSettings(BaseSettings):
    """Email template and recipient configuration."""
    
    from_address: str = Field(default="noreply@yulcom.com")
    from_name: str = Field(default="TenderAI BF")
    to_address: str = Field(default="tender-watch@yulcom.com")
    reply_to: Optional[str] = Field(default="support@yulcom.com")
    subject_prefix: str = Field(default="RFP Watch – Burkina Faso")
    signature: str = Field(default="YULCOM Technologies")
    logo_url: Optional[str] = Field(default=None)
    
    model_config = SettingsConfigDict(env_prefix='EMAIL_', case_sensitive=False)


class LLMSettings(BaseSettings):
    """Large Language Model configuration."""
    
    provider: str = Field(default="groq", validation_alias="LLM_PROVIDER")
    groq_api_key: SecretStr = Field(default="", validation_alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")
    openai_api_key: SecretStr = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4-turbo-preview", validation_alias="OPENAI_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1", validation_alias="OLLAMA_MODEL")
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
    confidence_threshold: float = Field(default=0.5, description="Minimum OCR confidence")

    model_config = SettingsConfigDict(env_prefix='OCR_', case_sensitive=False)


class SchedulerSettings(BaseSettings):
    """Scheduler configuration."""
    
    cron_schedule: str = Field(default="0 7 * * *")
    enabled: bool = Field(default=True)
    timezone: str = Field(default="Africa/Ouagadougou")
    max_concurrent_runs: int = Field(default=1, description="Max concurrent pipeline runs")
    run_on_startup: bool = Field(default=False, description="Run pipeline on startup")

    model_config = SettingsConfigDict(case_sensitive=False)


class SecuritySettings(BaseSettings):
    """Security configuration."""
    
    secret_key: SecretStr = Field(default="your-secret-key-here-change-in-production")
    admin_password: SecretStr = Field(default="change-me-in-production")
    session_timeout: int = Field(default=3600, description="Session timeout in seconds")

    model_config = SettingsConfigDict(case_sensitive=False)


class MonitoringSettings(BaseSettings):
    """Monitoring and observability configuration."""
    
    metrics_enabled: bool = Field(default=True)
    metrics_port: int = Field(default=9090)
    health_check_timeout: int = Field(default=30)
    # Logging
    log_level: str = "INFO"
    
    # JWT Authentication
    jwt_secret_key: str = Field(
        default="change-this-secret-key-in-production-use-openssl-rand-hex-32",
        description="Secret key for JWT token signing"
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours
    
    model_config = SettingsConfigDict(case_sensitive=False)


class ProcessingSettings(BaseSettings):
    """Processing limits and thresholds."""
    
    default_rate_limit: int = Field(default=10)
    min_relevance_score: float = Field(default=0.7)
    use_llm_classification: bool = Field(default=True, description="Use LLM for classification instead of keywords")
    max_items_per_run: int = Field(default=100)
    deduplication_threshold: float = Field(default=0.85)
    deduplication_method: str = Field(
        default="hash_similarity",
        description="Deduplication method: 'hash_only', 'similarity_only', 'hash_similarity', 'llm_only', 'hybrid'"
    )
    pdf_timeout: int = Field(default=120)
    max_file_size_mb: int = Field(default=50)

    model_config = SettingsConfigDict(case_sensitive=False)


class ClassificationSettings(BaseSettings):
    """Classification configuration."""
    
    relevant_keywords: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "it_services": [
                "informatique", "logiciel", "développement", "application",
                "système d'information", "base de données", "réseau",
                "cybersécurité", "cloud", "numérique", "digital", "site web",
                "plateforme", "e-gouvernement", "gestion électronique"
            ],
            "engineering": [
                "ingénierie", "génie civil", "infrastructure", "construction",
                "BTP", "routes", "bâtiment", "électricité", "télécommunications",
                "énergie", "hydraulique", "assainissement"
            ],
            "consulting": [
                "conseil", "consultance", "étude", "expertise",
                "assistance technique", "formation", "audit", "évaluation"
            ],
            "it_hardware": [
                "équipement informatique", "matériel informatique", "ordinateur",
                "serveur", "poste de travail", "matériel de bureau", "imprimante",
                "scanner", "photocopieur", "disque dur", "mémoire RAM", "processeur",
                "carte graphique", "carte mère", "alimentation électrique", "onduleur",
                "batterie", "câbles", "connecteurs", "accessoires informatiques",
                "écran", "moniteur", "clavier", "souris", "hub USB", "adaptateur",
                "routeur", "switch réseau", "modem", "point d'accès wifi", "disque SSD",
                "lecteur optique", "webcam", "microphone", "enceinte", "casque audio"
            ]
        },
        description="Keywords grouped by category for relevance classification"
    )
    
    model_config = SettingsConfigDict(case_sensitive=False)


class FetchSettings(BaseSettings):
    """HTTP fetching configuration."""
    
    user_agent: str = Field(
        default="TenderAI-BF/1.0",
        description="User-Agent header for HTTP requests"
    )
    timeout: int = Field(default=30, description="Default HTTP timeout in seconds")
    follow_redirects: bool = Field(default=True)
    max_retries: int = Field(default=3)

    model_config = SettingsConfigDict(env_prefix='FETCH_', case_sensitive=False)


class RAGChromaSettings(BaseSettings):
    """Chroma vector database settings for RAG."""
    
    persist_directory: str = Field(default="./data/chroma_db")
    collection_prefix: str = Field(default="tenders")
    host: Optional[str] = Field(default=None)
    port: Optional[int] = Field(default=None)
    track_metadata: List[str] = Field(default_factory=lambda: ["source", "date", "filename", "page_number", "tender_id"])
    vector_search_query: str = Field(
        default="Extraire les appels d'offres publics, entités, dates limites, et pertinence IT/Ingénierie",
        description="Query for vector similarity search (should match document language)"
    )
    llm_query_template: str = Field(default="Extract all tenders from the following documents")

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

    model_config = SettingsConfigDict(env_prefix='RAG_', case_sensitive=False)


class Settings(BaseSettings):
    """Main application settings."""
    
    app_name: str = Field(default="TenderAI BF")
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
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    
    # Sources configuration mode (added after nested settings)
    use_database_sources: bool = Field(
        default=False,
        description="If True, sync and use sources from database. If False, use only settings.yaml (dev mode)"
    )
    
    # Sources and recipients
    
    # External configuration
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    rate_limits: Dict[str, str] = Field(default_factory=dict)
    recipients: List[Dict[str, str]] = Field(default_factory=list)
    prompts: Dict[str, Any] = Field(default_factory=dict, description="LLM prompts templates from settings.yaml")
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)
    
    def __init__(self, **kwargs):
        """Initialize settings and load external configuration."""
        super().__init__(**kwargs)
        self._load_yaml_config()
    
    def _load_yaml_config(self) -> None:
        """Load configuration from settings.yaml if it exists."""
        yaml_path = Path("settings.yaml")
        if yaml_path.exists():
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    yaml_config = yaml.safe_load(f)
                
                # Expand environment variables in the entire config
                if yaml_config:
                    yaml_config = expand_env_vars(yaml_config)
                    # Update sources if present
                    if "sources" in yaml_config:
                        self.sources = yaml_config["sources"]
                    
                    # Update rate limits if present
                    if "rate_limits" in yaml_config:
                        self.rate_limits = yaml_config["rate_limits"]
                    
                    # Update recipients if present
                    if "recipients" in yaml_config:
                        self.recipients = yaml_config["recipients"]
                    
                    # Update prompts if present
                    if "prompts" in yaml_config:
                        self.prompts = yaml_config["prompts"]
                    
                    # Update scheduler if present
                    if "scheduler" in yaml_config:
                        scheduler_config = yaml_config["scheduler"]
                        if "cron_schedule" in scheduler_config:
                            self.scheduler.cron_schedule = scheduler_config["cron_schedule"]
                        if "timezone" in scheduler_config:
                            self.scheduler.timezone = scheduler_config["timezone"]
                    
                    # Update LLM provider if present
                    if "llm" in yaml_config:
                        llm_config = yaml_config["llm"]
                        if "provider" in llm_config:
                            self.llm.provider = llm_config["provider"]
                        if "ollama_base_url" in llm_config:
                            self.llm.ollama_base_url = llm_config["ollama_base_url"]
                        if "ollama_model" in llm_config:
                            self.llm.ollama_model = llm_config["ollama_model"]
                        if "groq_model" in llm_config:
                            self.llm.groq_model = llm_config["groq_model"]
                        if "openai_model" in llm_config:
                            self.llm.openai_model = llm_config["openai_model"]
                        if "temperature" in llm_config:
                            self.llm.temperature = llm_config["temperature"]
                        if "max_tokens" in llm_config:
                            self.llm.max_tokens = llm_config["max_tokens"]
                    
                    # Update OCR settings if present
                    if "ocr" in yaml_config:
                        ocr_config = yaml_config["ocr"]
                        if "enabled" in ocr_config:
                            self.ocr.enabled = ocr_config["enabled"]
                        if "language" in ocr_config:
                            self.ocr.language = ocr_config["language"]
                    
                    # Update classification keywords if present
                    if "classification" in yaml_config:
                        classification_config = yaml_config["classification"]
                        if "relevant_keywords" in classification_config:
                            self.classification.relevant_keywords = classification_config["relevant_keywords"]
                    
                    # Update processing settings if present
                    if "processing" in yaml_config:
                        processing_config = yaml_config["processing"]
                        if "min_relevance_score" in processing_config:
                            self.processing.min_relevance_score = processing_config["min_relevance_score"]
                        if "use_llm_classification" in processing_config:
                            self.processing.use_llm_classification = processing_config["use_llm_classification"]
                    
                    # Update RAG settings if present
                    if "rag" in yaml_config:
                        rag_config = yaml_config["rag"]
                        # Update top-level RAG settings
                        if "enabled" in rag_config:
                            self.rag.enabled = rag_config["enabled"]
                        if "chunk_size" in rag_config:
                            self.rag.chunk_size = rag_config["chunk_size"]
                        if "chunk_overlap" in rag_config:
                            self.rag.chunk_overlap = rag_config["chunk_overlap"]
                        if "top_k_results" in rag_config:
                            self.rag.top_k_results = rag_config["top_k_results"]
                        if "embedding_model" in rag_config:
                            self.rag.embedding_model = rag_config["embedding_model"]
                        # Update Chroma settings
                        if "chroma" in rag_config:
                            chroma_config = rag_config["chroma"]
                            if "vector_search_query" in chroma_config:
                                self.rag.chroma.vector_search_query = chroma_config["vector_search_query"]
                            if "llm_query_template" in chroma_config:
                                self.rag.chroma.llm_query_template = chroma_config["llm_query_template"]
                            

            except Exception as e:
                # Log warning but don't fail
                print(f"Warning: Could not load settings.yaml: {e}")
    
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
    
    def get_active_sources(self) -> List[Dict[str, Any]]:
        """Get only enabled sources."""
        return [source for source in self.sources if source.get("enabled", True)]


# Global settings instance
settings = Settings()