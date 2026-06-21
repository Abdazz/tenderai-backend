"""Pydantic schemas for data validation and serialization."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, validator


class SourceBase(BaseModel):
    """Base schema for Source."""

    name: str = Field(..., max_length=255)
    base_url: HttpUrl
    list_url: HttpUrl
    parser_type: str = Field(default="html", max_length=50)
    rate_limit: str = Field(default="10/m", pattern=r"^\d+/[smhd]$")
    enabled: bool = True
    patterns: dict[str, Any] | None = None


class SourceCreate(SourceBase):
    """Schema for creating a new Source."""

    country_id: int | None = None


class SourceUpdate(BaseModel):
    """Schema for updating a Source."""

    name: str | None = Field(None, max_length=255)
    base_url: HttpUrl | None = None
    list_url: HttpUrl | None = None
    parser_type: str | None = Field(None, max_length=50)
    rate_limit: str | None = Field(None, pattern=r"^\d+/[smhd]$")
    enabled: bool | None = None
    patterns: dict[str, Any] | None = None


class Source(SourceBase):
    """Schema for Source with all fields."""

    id: int
    country_id: int | None = None
    last_seen_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunBase(BaseModel):
    """Base schema for Run."""

    status: str = Field(
        ..., pattern="^(running|completed|completed_with_warnings|failed)$"
    )
    triggered_by: str = Field(default="scheduler", pattern="^(scheduler|manual|api)$")
    triggered_by_user: str | None = None


class RunCreate(RunBase):
    """Schema for creating a new Run."""

    id: str = Field(
        ..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )


class RunUpdate(BaseModel):
    """Schema for updating a Run."""

    status: str | None = Field(
        None, pattern="^(running|completed|completed_with_warnings|failed)$"
    )
    finished_at: datetime | None = None
    counts_json: dict[str, Any] | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    logs_url: HttpUrl | None = None
    report_url: HttpUrl | None = None


class Run(RunBase):
    """Schema for Run with all fields."""

    id: str
    started_at: datetime
    finished_at: datetime | None = None
    counts_json: dict[str, Any] | None = None
    error_message: str | None = None
    error_traceback: str | None = None
    logs_url: str | None = None
    report_url: str | None = None
    duration_seconds: float | None = None

    class Config:
        from_attributes = True


class NoticeBase(BaseModel):
    """Base schema for Notice."""

    title: str = Field(..., max_length=500)
    ref_no: str | None = Field(None, max_length=100)
    entity: str | None = Field(None, max_length=300)
    category: str | None = Field(None, max_length=100)
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    location: str | None = Field(None, max_length=200)
    budget_xof: float | None = Field(None, ge=0)
    currency: str | None = Field(None, max_length=10)
    description: str | None = None
    url: HttpUrl


class NoticeCreate(NoticeBase):
    """Schema for creating a new Notice."""

    id: str = Field(
        ..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    source_id: int
    run_id: str
    content_hash: str = Field(..., pattern=r"^[a-f0-9]{64}$")


class NoticeUpdate(BaseModel):
    """Schema for updating a Notice."""

    summary_fr: str | None = None
    summary_en: str | None = None
    relevance_score: float | None = Field(None, ge=0, le=1)
    is_relevant: bool | None = None
    classification_method: str | None = Field(None, max_length=50)
    is_duplicate: bool | None = None
    duplicate_of_id: str | None = None


class Notice(NoticeBase):
    """Schema for Notice with all fields."""

    id: str
    source_id: int
    run_id: str
    summary_fr: str | None = None
    summary_en: str | None = None
    relevance_score: float | None = None
    is_relevant: bool = False
    classification_method: str | None = None
    content_hash: str
    is_duplicate: bool = False
    duplicate_of_id: str | None = None
    created_at: datetime
    updated_at: datetime
    days_remaining: int | None = None

    class Config:
        from_attributes = True


class NoticeURLBase(BaseModel):
    """Base schema for NoticeURL."""

    url: HttpUrl
    url_type: str = Field(default="source", max_length=50)
    description: str | None = Field(None, max_length=200)


class NoticeURLCreate(NoticeURLBase):
    """Schema for creating a new NoticeURL."""

    notice_id: str


class NoticeURL(NoticeURLBase):
    """Schema for NoticeURL with all fields."""

    id: int
    notice_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class FileBase(BaseModel):
    """Base schema for File."""

    filename: str = Field(..., max_length=255)
    content_type: str = Field(..., max_length=100)
    size_bytes: int | None = Field(None, ge=0)
    kind: str = Field(..., max_length=50)
    description: str | None = Field(None, max_length=200)
    source_url: HttpUrl | None = None


class FileCreate(FileBase):
    """Schema for creating a new File."""

    id: str = Field(
        ..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    notice_id: str
    storage_key: str = Field(..., max_length=500)
    checksum: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")


class FileUpdate(BaseModel):
    """Schema for updating a File."""

    storage_url: str | None = None
    processed: bool | None = None
    ocr_text: str | None = None
    processing_error: str | None = None


class File(FileBase):
    """Schema for File with all fields."""

    id: str
    notice_id: str
    storage_key: str
    storage_url: str | None = None
    checksum: str | None = None
    processed: bool = False
    ocr_text: str | None = None
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RecipientBase(BaseModel):
    """Base schema for Recipient."""

    email: str = Field(..., max_length=255)
    name: str | None = Field(None, max_length=200)
    group: str = Field(default="default", max_length=50)
    enabled: bool = True
    preferences: dict[str, Any] | None = None

    @validator("email")
    def validate_email(cls, v):
        """Validate email format."""
        import re

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v.lower()


class RecipientCreate(RecipientBase):
    """Schema for creating a new Recipient."""

    country_id: int | None = None


class RecipientUpdate(BaseModel):
    """Schema for updating a Recipient."""

    name: str | None = Field(None, max_length=200)
    group: str | None = Field(None, max_length=50)
    enabled: bool | None = None
    preferences: dict[str, Any] | None = None


class Recipient(RecipientBase):
    """Schema for Recipient with all fields."""

    id: int
    last_sent_at: datetime | None = None
    bounce_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PipelineState(BaseModel):
    """Schema for LangGraph pipeline state."""

    run_id: str
    sources: list[Source] = Field(default_factory=list)
    discovered_links: list[str] = Field(default_factory=list)
    items_raw: list[dict[str, Any]] = Field(default_factory=list)
    items_parsed: list[Notice] = Field(default_factory=list)
    relevant_items: list[Notice] = Field(default_factory=list)
    unique_items: list[Notice] = Field(default_factory=list)
    summaries: dict[str, str] = Field(default_factory=dict)
    report_bytes: bytes | None = None
    report_url: str | None = None
    email_status: dict[str, Any] = Field(default_factory=dict)

    # Processing statistics
    stats: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class RunStatistics(BaseModel):
    """Schema for run statistics."""

    sources_checked: int = 0
    links_discovered: int = 0
    items_fetched: int = 0
    items_parsed: int = 0
    relevant_items: int = 0
    unique_items: int = 0
    reports_generated: int = 0
    emails_sent: int = 0
    errors_count: int = 0

    # Performance metrics
    fetch_time_seconds: float = 0
    parse_time_seconds: float = 0
    classify_time_seconds: float = 0
    dedupe_time_seconds: float = 0
    report_time_seconds: float = 0
    email_time_seconds: float = 0
    total_time_seconds: float = 0


class HealthCheck(BaseModel):
    """Schema for health check response."""

    status: str = Field(..., pattern="^(healthy|unhealthy|degraded)$")
    timestamp: datetime
    version: str
    environment: str

    # Component health
    database: bool = False
    storage: bool = False
    smtp: bool = False
    llm: bool = False

    # Additional info
    uptime_seconds: float = 0
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class Tender(BaseModel):
    """Schema for a single tender/RFP."""

    type: str = Field(
        default="appel_offres",
        description="Type d'élément : appel_offres, rectificatif, prorogation, communique, annulation, autre",
    )
    entity: str | None = Field(
        default="Inconnu", description="Entité ou organisme émettant l'appel d'offres"
    )
    reference: str | None = Field(
        default="Inconnu",
        description="Numéro de référence ou identifiant de l'appel d'offres",
    )
    tender_object: str | None = Field(
        default="Inconnu",
        description="Objet de l'appel d'offres tel qu'il apparaît dans le document (titre/phrase résumant l'objet principal)",
    )
    deadline: str | None = Field(
        default=None,
        description="Date limite de soumission au format DD-MM-YYYY (optionnelle)",
    )
    description: str | None = Field(
        default="",
        description="Description détaillée de l'appel d'offres incluant nature des travaux, lieux d'exécution, lots, conditions de participation, etc.",
    )
    category: str | None = Field(
        default="Autre",
        description="Catégorie de l'appel d'offres (IT, Ingénierie, Services, Biens, Travaux, Autre)",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Liste de 3 à 10 mots-clés pertinents directement liés au texte",
    )
    relevance_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score de pertinence (0.0 à 1.0) indiquant la clarté de l'appel d'offres dans le texte",
    )
    budget: str | None = Field(
        default=None,
        description="Budget ou montant explicitement mentionné (ex: 250 000 000 FCFA)",
    )
    location: str | None = Field(
        default=None,
        description="Localisation géographique (ville, région, pays) si identifiable",
    )
    source_url: str | None = Field(
        default=None, description="URL source ou référence si présente dans le texte"
    )


class TenderExtraction(BaseModel):
    """Container for extracted tenders."""

    tenders: list[Tender] = Field(
        default_factory=list, description="Liste des appels d'offres extraits"
    )
    total_extracted: int = Field(
        default=0, description="Nombre total d'appels d'offres extraits"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confiance globale de l'extraction"
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.total_extracted = len(self.tenders)
