"""SQLAlchemy ORM models for TenderAI BF."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class Source(Base):
    """Source websites and portals for RFP/tender monitoring."""

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    base_url = Column(String(500), nullable=False)
    list_url = Column(String(500), nullable=False)
    parser_type = Column(
        String(50), nullable=False, default="html"
    )  # html, pdf, html-pdf-mixed

    # Rate limiting and behavior
    rate_limit = Column(
        String(20), nullable=False, default="10/m"
    )  # requests per minute
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)

    # Parsing configuration (stored as JSON)
    patterns = Column(JSON, nullable=True)  # CSS selectors, XPath, regex patterns

    # Tracking
    last_seen_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    # Relationships
    notices = relationship(
        "Notice", back_populates="source", cascade="all, delete-orphan"
    )
    country = relationship("Country", back_populates="sources")

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', enabled={self.enabled})>"


class Run(Base):
    """Pipeline execution runs."""

    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, index=True)  # UUID
    # Allowed values: running, completed, completed_with_warnings, failed
    status = Column(String(40), nullable=False, index=True)

    # Timing
    started_at = Column(DateTime, nullable=False, default=func.now())
    finished_at = Column(DateTime, nullable=True)

    # Statistics (stored as JSON)
    counts_json = Column(JSON, nullable=True)  # sources_checked, notices_found, etc.

    # Error information
    error_message = Column(Text, nullable=True)
    error_traceback = Column(Text, nullable=True)

    # Logs and artifacts
    logs_url = Column(String(500), nullable=True)  # MinIO URL to log file
    report_url = Column(String(500), nullable=True)  # MinIO URL to generated report

    # Trigger information
    triggered_by = Column(
        String(50), nullable=False, default="scheduler"
    )  # scheduler, manual, api
    triggered_by_user = Column(String(100), nullable=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)

    # Relationships
    notices = relationship("Notice", back_populates="run")
    country = relationship("Country", back_populates="runs")

    def __repr__(self) -> str:
        return f"<Run(id='{self.id}', status='{self.status}', started_at={self.started_at})>"

    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class Notice(Base):
    """Individual RFP/tender notices discovered and processed."""

    __tablename__ = "notices"

    id = Column(String(36), primary_key=True, index=True)  # UUID
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False, index=True)

    # Core fields
    title = Column(String(500), nullable=False, index=True)
    ref_no = Column(String(100), nullable=True, index=True)  # Reference number
    entity = Column(String(300), nullable=True, index=True)  # Publishing entity
    category = Column(
        String(100), nullable=True, index=True
    )  # Biens, Services, Travaux

    # Dates
    published_at = Column(DateTime, nullable=True, index=True)
    deadline_at = Column(DateTime, nullable=True, index=True)

    # Location and budget
    location = Column(String(200), nullable=True, index=True)  # Province, region
    budget_xof = Column(Float, nullable=True, index=True)  # Budget in XOF
    currency = Column(String(10), nullable=True)  # Original currency

    # Content
    description = Column(Text, nullable=True)
    summary_fr = Column(Text, nullable=True)  # Generated French summary
    summary_en = Column(Text, nullable=True)  # Optional English summary

    # Processing
    relevance_score = Column(Float, nullable=True, index=True)
    is_relevant = Column(Boolean, nullable=False, default=False, index=True)
    classification_method = Column(String(50), nullable=True)  # rules, ml, hybrid

    # Deduplication
    content_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hash
    is_duplicate = Column(Boolean, nullable=False, default=False, index=True)
    duplicate_of_id = Column(String(36), ForeignKey("notices.id"), nullable=True)

    # Original URL
    url = Column(String(1000), nullable=False)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    # Relationships
    source = relationship("Source", back_populates="notices")
    run = relationship("Run", back_populates="notices")
    notice_urls = relationship(
        "NoticeURL", back_populates="notice", cascade="all, delete-orphan"
    )
    files = relationship("File", back_populates="notice", cascade="all, delete-orphan")
    duplicate_of = relationship("Notice", remote_side=[id])

    def __repr__(self) -> str:
        return f"<Notice(id='{self.id}', title='{self.title[:50]}...', is_relevant={self.is_relevant})>"

    @property
    def days_remaining(self) -> int | None:
        """Calculate days remaining until deadline."""
        if self.deadline_at:
            now = datetime.utcnow()
            if self.deadline_at > now:
                return (self.deadline_at - now).days
            else:
                return 0  # Expired
        return None


class NoticeURL(Base):
    """Additional URLs associated with a notice (multiple sources, documents, etc.)."""

    __tablename__ = "notice_urls"

    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(String(36), ForeignKey("notices.id"), nullable=False, index=True)
    url = Column(String(1000), nullable=False)
    url_type = Column(
        String(50), nullable=False, default="source"
    )  # source, document, detail
    description = Column(String(200), nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())

    # Relationships
    notice = relationship("Notice", back_populates="notice_urls")

    def __repr__(self) -> str:
        return f"<NoticeURL(id={self.id}, url='{self.url[:50]}...', type='{self.url_type}')>"


class File(Base):
    """Files and documents associated with notices (PDFs, images, etc.)."""

    __tablename__ = "files"

    id = Column(String(36), primary_key=True, index=True)  # UUID
    notice_id = Column(String(36), ForeignKey("notices.id"), nullable=False, index=True)

    # File information
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=True)

    # File type and purpose
    kind = Column(
        String(50), nullable=False, index=True
    )  # pdf, image, document, snapshot
    description = Column(String(200), nullable=True)

    # Storage
    storage_key = Column(String(500), nullable=False)  # MinIO key
    storage_url = Column(String(1000), nullable=True)  # Public URL if available
    checksum = Column(String(64), nullable=True)  # SHA-256 checksum

    # Processing status
    processed = Column(Boolean, nullable=False, default=False)
    ocr_text = Column(Text, nullable=True)  # Extracted text via OCR
    processing_error = Column(Text, nullable=True)

    # Original source
    source_url = Column(String(1000), nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    # Relationships
    notice = relationship("Notice", back_populates="files")

    def __repr__(self) -> str:
        return f"<File(id='{self.id}', filename='{self.filename}', kind='{self.kind}')>"


class Recipient(Base):
    """Email recipients for report distribution."""

    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=True)

    # Grouping and preferences
    group = Column(
        String(50), nullable=False, default="default", index=True
    )  # to, cc, bcc
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)

    # Relationships
    country = relationship("Country", back_populates="recipients")

    # Preferences (stored as JSON)
    preferences = Column(JSON, nullable=True)  # frequency, format, etc.

    # Tracking
    last_sent_at = Column(DateTime, nullable=True)
    bounce_count = Column(Integer, nullable=False, default=0)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Recipient(id={self.id}, email='{self.email}', group='{self.group}')>"


class User(Base):
    """Application users with role-based access."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    username = Column(String(64), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(15), nullable=False, default="viewer")  # super_admin | admin | viewer
    is_active = Column(Boolean, nullable=False, default=True)
    password_reset_required = Column(Boolean, nullable=False, default=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    last_login_at = Column(DateTime, nullable=True)

    country = relationship("Country", foreign_keys=[country_id])

    def __repr__(self) -> str:
        return f"<User(username='{self.username}', role='{self.role}')>"


class AppSettings(Base):
    """Mutable operational settings persisted in DB."""

    __tablename__ = "app_settings"

    section = Column(String(64), primary_key=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AppSettings(section='{self.section}')>"


class Country(Base):
    """Countries with independent pipeline configurations."""

    __tablename__ = "countries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(10), nullable=False, unique=True, index=True)
    locale = Column(String(10), nullable=False, default="fr")
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    settings = relationship(
        "CountrySettings", back_populates="country", cascade="all, delete-orphan"
    )
    sources = relationship("Source", back_populates="country")
    runs = relationship("Run", back_populates="country")
    recipients = relationship("Recipient", back_populates="country")

    def __repr__(self) -> str:
        return (
            f"<Country(code='{self.code}', name='{self.name}', active={self.active})>"
        )


class CountrySettings(Base):
    """Per-country operational settings, one row per section."""

    __tablename__ = "country_settings"

    country_id = Column(Integer, ForeignKey("countries.id"), primary_key=True)
    section = Column(String(64), primary_key=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by = Column(Text, nullable=True)

    country = relationship("Country", back_populates="settings")

    def __repr__(self) -> str:
        return (
            f"<CountrySettings(country_id={self.country_id}, section='{self.section}')>"
        )


class Company(Base):
    """A tenant company using TenderAI as a service."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), nullable=False, unique=True, index=True)
    active = Column(Boolean, nullable=False, default=True, index=True)

    # Branding — falls back to defaults in report/email code when null
    logo_url = Column(String(500), nullable=True)
    subject_prefix = Column(String(100), nullable=True)
    signature = Column(String(255), nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    country_subscriptions = relationship(
        "CompanyCountrySubscription",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    settings = relationship(
        "CompanySettings", back_populates="company", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Company(slug='{self.slug}', name='{self.name}', active={self.active})>"


class CompanyCountrySubscription(Base):
    """Which countries (from the shared catalog) a company monitors."""

    __tablename__ = "company_country_subscriptions"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    country_id = Column(Integer, ForeignKey("countries.id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())

    company = relationship("Company", back_populates="country_subscriptions")
    country = relationship("Country")

    def __repr__(self) -> str:
        return (
            f"<CompanyCountrySubscription(company_id={self.company_id}, "
            f"country_id={self.country_id}, enabled={self.enabled})>"
        )


class CompanySettings(Base):
    """Per-company operational settings, one row per section.

    Sections: classification (relevant_keywords, min_relevance_score, LLM
    prompts), scheduler (delivery cron_schedule, timezone, run_on_startup),
    email (subject_prefix/signature overrides). Does NOT include an `llm`
    section — LLM provider/keys stay global (AppSettings/env).
    """

    __tablename__ = "company_settings"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    section = Column(String(64), primary_key=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    updated_by = Column(Text, nullable=True)

    company = relationship("Company", back_populates="settings")

    def __repr__(self) -> str:
        return f"<CompanySettings(company_id={self.company_id}, section='{self.section}')>"


class CompanyNoticeStatus(Base):
    """Per-company classification result for a shared Notice.

    A notice with no row here for a given company hasn't been classified/
    seen by that company yet — this absence is the delivery cursor consumed
    by the delivery pipeline. Unique on (company_id, notice_id).
    """

    __tablename__ = "company_notice_status"

    id = Column(String(36), primary_key=True, index=True)  # UUID, caller-supplied
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    notice_id = Column(String(36), ForeignKey("notices.id"), nullable=False, index=True)

    is_relevant = Column(Boolean, nullable=False, default=False)
    relevance_score = Column(Float, nullable=True)
    classification_method = Column(String(50), nullable=True)

    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "notice_id", name="uq_company_notice"),
    )

    company = relationship("Company")
    notice = relationship("Notice")

    def __repr__(self) -> str:
        return (
            f"<CompanyNoticeStatus(company_id={self.company_id}, "
            f"notice_id='{self.notice_id}', is_relevant={self.is_relevant})>"
        )
