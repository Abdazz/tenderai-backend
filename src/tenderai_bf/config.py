"""Configuration management using Pydantic Settings."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic.types import SecretStr


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
    
    provider: str = Field(default="groq")
    groq_api_key: SecretStr = Field(default="")
    groq_model: str = Field(default="llama-3.1-70b-versatile")
    openai_api_key: SecretStr = Field(default="")
    openai_model: str = Field(default="gpt-4-turbo-preview")
    temperature: float = Field(default=0.1, description="LLM temperature")
    max_tokens: int = Field(default=2048, description="Max response tokens")
    timeout: int = Field(default=60, description="LLM request timeout")

    model_config = SettingsConfigDict(env_prefix='LLM_', case_sensitive=False)


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
    max_items_per_run: int = Field(default=100)
    deduplication_threshold: float = Field(default=0.85)
    pdf_timeout: int = Field(default=120)
    max_file_size_mb: int = Field(default=50)

    model_config = SettingsConfigDict(case_sensitive=False)


class Settings(BaseSettings):
    """Main application settings."""
    
    app_name: str = Field(default="TenderAI BF")
    app_version: str = Field(default="0.1.0")
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    
    # Sub-configurations
    database: DatabaseSettings = DatabaseSettings()
    minio: MinIOSettings = MinIOSettings()
    smtp: SMTPSettings = SMTPSettings()
    email: EmailSettings = EmailSettings()
    llm: LLMSettings = LLMSettings()
    ocr: OCRSettings = OCRSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    security: SecuritySettings = SecuritySettings()
    monitoring: MonitoringSettings = MonitoringSettings()
    processing: ProcessingSettings = ProcessingSettings()
    
    # External configuration
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    rate_limits: Dict[str, str] = Field(default_factory=dict)
    recipients: List[Dict[str, str]] = Field(default_factory=list)
    
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
                    
                if yaml_config:
                    # Update sources if present
                    if "sources" in yaml_config:
                        self.sources = yaml_config["sources"]
                    
                    # Update rate limits if present
                    if "rate_limits" in yaml_config:
                        self.rate_limits = yaml_config["rate_limits"]
                    
                    # Update recipients if present
                    if "recipients" in yaml_config:
                        self.recipients = yaml_config["recipients"]
                    
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
                    
                    # Update OCR settings if present
                    if "ocr" in yaml_config:
                        ocr_config = yaml_config["ocr"]
                        if "enabled" in ocr_config:
                            self.ocr.enabled = ocr_config["enabled"]
                        if "language" in ocr_config:
                            self.ocr.language = ocr_config["language"]
                            
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