# Multi-Company Data Model & Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `Company` tenant axis to the data model — four new tables, three modified tables, one Alembic migration, and a `CompanyStore` data-access layer — with YULCOM Technologies seeded as the first company. This is the foundation every later plan (pipeline split, auth/API, frontend) depends on.

**Architecture:** Mirrors the existing `Country`/`CountrySettings`/`CountryStore` pattern one level up. `Notice` and `Source` stay untouched (shared harvest pool). `Run`, `Recipient`, `User` each gain a nullable `company_id`. A new `CompanyNoticeStatus` table holds per-company classification results and doubles as the delivery cursor (absence of a row = not yet processed for that company).

**Tech Stack:** SQLAlchemy (declarative `Column`/`ForeignKey` style, not `Mapped[]`), Alembic migrations, pytest with an in-memory SQLite fixture (`Base.metadata.create_all`), PostgreSQL for the real migration run.

**Spec:** `docs/superpowers/specs/2026-08-23-multi-company-design.md` (Section 1 — Data Model, Section 5 — Migration & Rollout)

## Global Constraints

- New tables/columns must not break existing queries — every new FK column is `nullable=True` except where the spec explicitly says otherwise.
- Follow the existing migration style exactly: idempotent (`_table_exists`/`_column_exists` guards), safe to re-run, mirrors `alembic/versions/0003_add_countries.py`.
- Follow the existing model style exactly: classic `Column(...)` declarative style (not SQLAlchemy 2.0 `Mapped[]`), matching every other class in `src/tenderai_bf/models.py`.
- pytest tests target the ORM layer via `Base.metadata.create_all(engine)` on in-memory SQLite — they do **not** execute the Alembic migration. Migration correctness is verified separately by running `alembic upgrade head` against the real dev Postgres DB (a manual step in each task, not a pytest step).
- `User.role` string values are renamed `admin`→`company_admin` (13 chars) and `viewer`→`company_viewer` (14 chars) — both fit the existing `String(15)` column, no length change needed.
- The current Alembic head is `0012` (`alembic/versions/0012_recipients_unique_per_country.py`). The new migration is `0013_add_companies.py`, `down_revision = "0012"`, built up incrementally across tasks (one file, multiple edits) — same file structure precedent as `0003_add_countries.py`.

---

## Task 1: `Company` model, table, and YULCOM seed row

**Files:**
- Modify: `src/tenderai_bf/models.py` (append `Company` class at end of file, after `CountrySettings`)
- Create: `alembic/versions/0013_add_companies.py`
- Create: `tests/test_company_store.py`

**Interfaces:**
- Produces: `Company` ORM class — `id: int`, `name: str`, `slug: str` (unique), `active: bool`, `logo_url: str | None`, `subject_prefix: str | None`, `signature: str | None`, `created_at`, `updated_at`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_company_store.py`:

```python
import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.db import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_company_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("companies")}
    assert {
        "id",
        "name",
        "slug",
        "active",
        "logo_url",
        "subject_prefix",
        "signature",
        "created_at",
        "updated_at",
    }.issubset(cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL — `sqlalchemy.exc.NoSuchTableError: companies` (table doesn't exist because the model doesn't exist yet)

- [ ] **Step 3: Add the `Company` model**

Append to `src/tenderai_bf/models.py` (after the `CountrySettings` class, end of file):

```python


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

    def __repr__(self) -> str:
        return f"<Company(slug='{self.slug}', name='{self.name}', active={self.active})>"
```

**Do not add `settings`/`country_subscriptions` relationships to `Company` in this task.** They reference `CompanySettings`/`CompanyCountrySubscription`, which don't exist until Tasks 3/2. SQLAlchemy's mapper configuration is process-wide and lazy — the first ORM query issued *anywhere* in the process (including pre-existing, unrelated tests) forces `configure_mappers()` to resolve every pending relationship, and a relationship string that can't be resolved fails configuration for the whole registry, breaking every ORM-backed test and endpoint until the target class exists. Task 2 adds the `country_subscriptions` relationship back onto `Company` in the same commit that defines `CompanyCountrySubscription`; Task 3 does the same for `settings`/`CompanySettings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Write the migration — companies table + YULCOM seed**

Create `alembic/versions/0013_add_companies.py`:

```python
"""add_companies

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-23

Adds the Company tenant axis on top of the existing Country abstraction.
Seeds YULCOM Technologies as the first company (tenant zero). Idempotent —
safe to re-run.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    return table_name in insp.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    insp = Inspector.from_engine(conn)
    try:
        return any(c["name"] == column_name for c in insp.get_columns(table_name))
    except sa.exc.NoSuchTableError:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create companies table (idempotent: may already exist from create_all)
    if not _table_exists(bind, "companies"):
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("logo_url", sa.String(500), nullable=True),
            sa.Column("subject_prefix", sa.String(100), nullable=True),
            sa.Column("signature", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("slug", name="uq_companies_slug"),
        )

    # 2. Seed YULCOM Technologies as the first company (idempotent)
    existing = bind.execute(
        sa.text("SELECT id FROM companies WHERE slug = 'yulcom'")
    ).fetchone()
    if existing is None:
        op.execute(
            "INSERT INTO companies (name, slug, active, created_at, updated_at) "
            "VALUES ('YULCOM Technologies', 'yulcom', true, NOW(), NOW())"
        )


def downgrade() -> None:
    op.drop_table("companies")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: migration `0013` applies with no errors; verify with:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT id, name, slug, active FROM companies;"`
Expected output: one row — `YULCOM Technologies | yulcom | t`

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add Company table, seed YULCOM as first tenant"
```

---

## Task 2: `CompanyCountrySubscription` model, table, and YULCOM subscriptions

**Files:**
- Modify: `src/tenderai_bf/models.py` (append `CompanyCountrySubscription` class)
- Modify: `alembic/versions/0013_add_companies.py` (append table + subscribe YULCOM to all active countries)
- Modify: `tests/test_company_store.py` (append test)

**Interfaces:**
- Consumes: `Company` (Task 1), `Country` (existing, `src/tenderai_bf/models.py`).
- Produces: `CompanyCountrySubscription` ORM class — `company_id: int`, `country_id: int` (composite PK), `enabled: bool`, `created_at`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_company_country_subscription_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_country_subscriptions")}
    assert {"company_id", "country_id", "enabled", "created_at"}.issubset(cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL — `NoSuchTableError: company_country_subscriptions`

- [ ] **Step 3: Add the `CompanyCountrySubscription` model**

Append to `src/tenderai_bf/models.py` (after `Company`):

```python


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
```

Also add the back-reference onto `Company` (Task 1 deliberately omitted it — a relationship string pointing at a class that doesn't exist yet breaks SQLAlchemy's process-wide mapper configuration, so it lands here instead, in the same commit as `CompanyCountrySubscription` itself). In `src/tenderai_bf/models.py`, inside the `Company` class, add before its `__repr__` method:

```python
    country_subscriptions = relationship(
        "CompanyCountrySubscription",
        back_populates="company",
        cascade="all, delete-orphan",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Extend the migration — subscriptions table + YULCOM subscribed to all active countries**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()` (after the company seed block):

```python
    # 3. Create company_country_subscriptions table (idempotent)
    if not _table_exists(bind, "company_country_subscriptions"):
        op.create_table(
            "company_country_subscriptions",
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("country_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("company_id", "country_id"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_ccs_company_id"
            ),
            sa.ForeignKeyConstraint(
                ["country_id"], ["countries.id"], name="fk_ccs_country_id"
            ),
        )

    # 4. Subscribe YULCOM to every currently-active country (idempotent)
    op.execute("""
        INSERT INTO company_country_subscriptions (company_id, country_id, enabled, created_at)
        SELECT
            (SELECT id FROM companies WHERE slug = 'yulcom'),
            c.id,
            true,
            NOW()
        FROM countries c
        WHERE c.active = true
        AND NOT EXISTS (
            SELECT 1 FROM company_country_subscriptions ccs
            WHERE ccs.company_id = (SELECT id FROM companies WHERE slug = 'yulcom')
            AND ccs.country_id = c.id
        )
    """)
```

And add the corresponding `downgrade()` line (before `op.drop_table("companies")`):

```python
    op.drop_table("company_country_subscriptions")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. Verify:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT ccs.country_id, c.name FROM company_country_subscriptions ccs JOIN countries c ON c.id = ccs.country_id;"`
Expected: one row per active country (BF, CI, SN, CA at time of writing).

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add CompanyCountrySubscription, subscribe YULCOM to all active countries"
```

---

## Task 3: `CompanySettings` model, table, and YULCOM seed from `AppSettings`

**Files:**
- Modify: `src/tenderai_bf/models.py` (append `CompanySettings` class)
- Modify: `alembic/versions/0013_add_companies.py` (append table + seed from `AppSettings`)
- Modify: `tests/test_company_store.py` (append test)

**Interfaces:**
- Consumes: `Company` (Task 1), `AppSettings` (existing).
- Produces: `CompanySettings` ORM class — `company_id: int`, `section: str` (composite PK), `data: dict` (JSON), `updated_at`, `updated_by: str | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_company_settings_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_settings")}
    assert {"company_id", "section", "data", "updated_at", "updated_by"}.issubset(cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL — `NoSuchTableError: company_settings`

- [ ] **Step 3: Add the `CompanySettings` model**

Append to `src/tenderai_bf/models.py` (after `CompanyCountrySubscription`):

```python


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
```

Also add the back-reference onto `Company` (deferred from Task 1 for the same reason as Task 2's `country_subscriptions` — see Task 1's note). In `src/tenderai_bf/models.py`, inside the `Company` class, add before its `__repr__` method (alongside the `country_subscriptions` line Task 2 already added there):

```python
    settings = relationship(
        "CompanySettings", back_populates="company", cascade="all, delete-orphan"
    )
```

- [ ] **Step 4: Run test to verify it passes, and verify the mapper registry resolves cleanly**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

This task is the last one that leaves `Company` with an unresolved forward reference (Task 1 deliberately omitted both relationships; Task 2 restored `country_subscriptions`; this step restores `settings`, the last one). Add one more test to `tests/test_company_store.py` to lock this in as a regression guard — it must fail if any relationship on any model in the registry can't resolve:

```python
def test_sqlalchemy_mapper_registry_configures_cleanly(db):
    """Guards against the Task 1 regression: a relationship() referencing a
    not-yet-existing class breaks configure_mappers() for the whole process,
    not just the model that declares it."""
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
```

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Extend the migration — settings table + seed YULCOM classification/scheduler from `AppSettings`**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()`:

```python
    # 5. Create company_settings table (idempotent)
    if not _table_exists(bind, "company_settings"):
        op.create_table(
            "company_settings",
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("section", sa.String(64), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_by", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("company_id", "section"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_company_settings_company_id"
            ),
        )

    # 6. Seed YULCOM's classification section from AppSettings["classification"],
    #    consolidating min_relevance_score (today under AppSettings["pipeline"])
    #    into the same company-level "classification" section (idempotent).
    cs_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM company_settings WHERE company_id = "
            "(SELECT id FROM companies WHERE slug = 'yulcom') AND section = 'classification'"
        )
    ).scalar()
    if cs_count == 0:
        classification_row = bind.execute(
            sa.text("SELECT data FROM app_settings WHERE section = 'classification'")
        ).fetchone()
        pipeline_row = bind.execute(
            sa.text("SELECT data FROM app_settings WHERE section = 'pipeline'")
        ).fetchone()
        if classification_row is not None:
            import json as _json

            merged = dict(classification_row[0])
            if pipeline_row is not None and "min_relevance_score" in pipeline_row[0]:
                merged["min_relevance_score"] = pipeline_row[0]["min_relevance_score"]
            # Plain string substitution, not a bind param: the JSON payload comes
            # from our own app_settings row, not user input, so this is safe, and
            # it sidesteps dialect-specific JSON bind-param handling entirely.
            merged_json = _json.dumps(merged).replace("'", "''")
            op.execute(
                "INSERT INTO company_settings (company_id, section, data, updated_at, updated_by) "
                "VALUES ((SELECT id FROM companies WHERE slug = 'yulcom'), "
                f"'classification', '{merged_json}'::json, NOW(), 'migration_0013')"
            )

    # 7. Seed YULCOM's scheduler section from AppSettings["scheduler"] (idempotent)
    sched_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM company_settings WHERE company_id = "
            "(SELECT id FROM companies WHERE slug = 'yulcom') AND section = 'scheduler'"
        )
    ).scalar()
    if sched_count == 0:
        op.execute("""
            INSERT INTO company_settings (company_id, section, data, updated_at, updated_by)
            SELECT
                (SELECT id FROM companies WHERE slug = 'yulcom'),
                'scheduler',
                data,
                NOW(),
                'migration_0013'
            FROM app_settings
            WHERE section = 'scheduler'
        """)
```

Add to `downgrade()` (before `op.drop_table("company_country_subscriptions")` — the block Task 2 added):

```python
    op.drop_table("company_settings")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. Verify:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT section, data->'min_relevance_score' FROM company_settings WHERE company_id = (SELECT id FROM companies WHERE slug='yulcom');"`
Expected: a `classification` row with `min_relevance_score` present (e.g. `0.65`), and a `scheduler` row.

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add CompanySettings, seed YULCOM classification/scheduler config"
```

---

## Task 4: `CompanyNoticeStatus` model, table, and historical backfill

**Files:**
- Modify: `src/tenderai_bf/models.py` (append `CompanyNoticeStatus` class; add `UniqueConstraint` to the sqlalchemy import line)
- Modify: `alembic/versions/0013_add_companies.py` (append table + backfill from `Notice`)
- Modify: `tests/test_company_store.py` (append test)

**Interfaces:**
- Consumes: `Company` (Task 1), `Notice` (existing).
- Produces: `CompanyNoticeStatus` ORM class — `id: str` (UUID, caller-supplied like `Notice.id`/`Run.id`), `company_id: int`, `notice_id: str`, `is_relevant: bool`, `relevance_score: float | None`, `classification_method: str | None`, `delivered_at`, `created_at`. Unique on `(company_id, notice_id)` — this pair's *absence* is the per-company delivery cursor consumed by the delivery pipeline (Plan #2).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_company_notice_status_table_has_expected_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("company_notice_status")}
    assert {
        "id",
        "company_id",
        "notice_id",
        "is_relevant",
        "relevance_score",
        "classification_method",
        "delivered_at",
        "created_at",
    }.issubset(cols)


def test_company_notice_status_unique_per_company_and_notice(db):
    import uuid

    from tenderai_bf.models import Company, CompanyNoticeStatus, Notice, Run, Source

    company = Company(name="Test Co", slug="test-co")
    db.add(company)
    source = Source(name="src", base_url="https://x", list_url="https://x/list", parser_type="html")
    db.add(source)
    run = Run(id=str(uuid.uuid4()), status="completed", triggered_by="manual")
    db.add(run)
    db.commit()

    notice = Notice(
        id=str(uuid.uuid4()),
        source_id=source.id,
        run_id=run.id,
        title="Test notice",
        content_hash="a" * 64,
        url="https://x/notice/1",
    )
    db.add(notice)
    db.commit()

    status = CompanyNoticeStatus(
        id=str(uuid.uuid4()),
        company_id=company.id,
        notice_id=notice.id,
        is_relevant=True,
        relevance_score=0.9,
    )
    db.add(status)
    db.commit()

    dupe = CompanyNoticeStatus(
        id=str(uuid.uuid4()),
        company_id=company.id,
        notice_id=notice.id,
        is_relevant=False,
    )
    db.add(dupe)
    with pytest.raises(Exception):
        db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL — `NoSuchTableError: company_notice_status`

- [ ] **Step 3: Add the `CompanyNoticeStatus` model**

First, add `UniqueConstraint` to the existing sqlalchemy import at the top of `src/tenderai_bf/models.py`:

```python
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
```

Then append to `src/tenderai_bf/models.py` (after `CompanySettings`):

```python


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS (both new tests)

- [ ] **Step 5: Extend the migration — table + backfill from historical `Notice` data**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()`:

```python
    # 8. Create company_notice_status table (idempotent)
    if not _table_exists(bind, "company_notice_status"):
        op.create_table(
            "company_notice_status",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("notice_id", sa.String(36), nullable=False),
            sa.Column("is_relevant", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("relevance_score", sa.Float(), nullable=True),
            sa.Column("classification_method", sa.String(50), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("company_id", "notice_id", name="uq_company_notice"),
            sa.ForeignKeyConstraint(
                ["company_id"], ["companies.id"], name="fk_cns_company_id"
            ),
            sa.ForeignKeyConstraint(
                ["notice_id"], ["notices.id"], name="fk_cns_notice_id"
            ),
        )

    # 9. Backfill from historical Notice classification, tagged to YULCOM (idempotent)
    if _table_exists(bind, "notices"):
        op.execute("""
            INSERT INTO company_notice_status
                (id, company_id, notice_id, is_relevant, relevance_score, classification_method, delivered_at, created_at)
            SELECT
                gen_random_uuid()::text,
                (SELECT id FROM companies WHERE slug = 'yulcom'),
                n.id,
                COALESCE(n.is_relevant, false),
                n.relevance_score,
                n.classification_method,
                n.created_at,
                n.created_at
            FROM notices n
            WHERE NOT EXISTS (
                SELECT 1 FROM company_notice_status cns
                WHERE cns.company_id = (SELECT id FROM companies WHERE slug = 'yulcom')
                AND cns.notice_id = n.id
            )
        """)
```

And add to `downgrade()` (before the `company_settings` drop):

```python
    op.drop_table("company_notice_status")
```

Note: `gen_random_uuid()` requires the `pgcrypto` extension (commonly already enabled — verify in Step 6). If it errors, replace with Python-side UUID generation in a loop instead of a single `INSERT ... SELECT`, using `uuid.uuid4()` per row.

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. If `gen_random_uuid()` is unavailable, run `docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"` first, then retry.

Verify (this dev DB's `notices` table is currently empty, so 0 rows is the expected/correct result here — this confirms the backfill runs cleanly against an empty pool, not that it worked against real data):
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT COUNT(*) FROM company_notice_status;"`

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add CompanyNoticeStatus, backfill historical classification for YULCOM"
```

---

## Task 5: `Run.run_type` and `Run.company_id`

**Files:**
- Modify: `src/tenderai_bf/models.py:67-110` (the `Run` class)
- Modify: `alembic/versions/0013_add_companies.py`
- Modify: `tests/test_company_store.py`

**Interfaces:**
- Consumes: `Company` (Task 1).
- Produces: `Run.run_type: str` (`"harvest"` | `"delivery"`, default `"harvest"`), `Run.company_id: int | None` (null for harvest runs).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_run_has_run_type_and_company_id_columns(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("runs")}
    assert {"run_type", "company_id"}.issubset(cols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL — `assert {'run_type', 'company_id'}.issubset(cols)` raises `AssertionError`

- [ ] **Step 3: Add the columns to `Run`**

In `src/tenderai_bf/models.py`, find the `Run` class (around line 67-110). Add after the existing `country_id` column (around line 96):

```python
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)
    run_type = Column(String(20), nullable=False, default="harvest")  # harvest | delivery
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
```

Add to the `Run` class's relationships block (near `country = relationship("Country", back_populates="runs")`):

```python
    company = relationship("Company")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Extend the migration**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()`:

```python
    # 10. runs.run_type and runs.company_id
    if _table_exists(bind, "runs"):
        if not _column_exists(bind, "runs", "run_type"):
            op.add_column(
                "runs",
                sa.Column("run_type", sa.String(20), nullable=False, server_default="harvest"),
            )
        if not _column_exists(bind, "runs", "company_id"):
            op.add_column("runs", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_runs_company_id", "runs", "companies", ["company_id"], ["id"]
            )
```

Add at the very top of `downgrade()` — before every other line already in that function (this is migration `0013`'s own `downgrade()`; do not confuse with `runs.country_id`, which belongs to migration `0003` and is untouched here):

```python
    op.drop_constraint("fk_runs_company_id", "runs", type_="foreignkey")
    op.drop_column("runs", "company_id")
    op.drop_column("runs", "run_type")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. Verify:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT run_type, company_id, COUNT(*) FROM runs GROUP BY run_type, company_id;"`
Expected: all existing rows show `run_type = 'harvest'`, `company_id` is `NULL`.

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add Run.run_type and Run.company_id"
```

---

## Task 6: `Recipient.company_id`, backfilled to YULCOM

**Files:**
- Modify: `src/tenderai_bf/models.py:255-288` (the `Recipient` class)
- Modify: `alembic/versions/0013_add_companies.py`
- Modify: `tests/test_company_store.py`

**Interfaces:**
- Consumes: `Company` (Task 1).
- Produces: `Recipient.company_id: int | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_recipient_has_company_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("recipients")}
    assert "company_id" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Add the column to `Recipient`**

In `src/tenderai_bf/models.py`, find the `Recipient` class (around line 255-288). Add after the existing `country_id` column (around line 269):

```python
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
```

Add to the relationships block (near `country = relationship("Country", back_populates="recipients")`):

```python
    company = relationship("Company")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Extend the migration**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()`:

```python
    # 11. recipients.company_id — backfilled to YULCOM
    if _table_exists(bind, "recipients"):
        if not _column_exists(bind, "recipients", "company_id"):
            op.add_column("recipients", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_recipients_company_id", "recipients", "companies", ["company_id"], ["id"]
            )
        op.execute(
            "UPDATE recipients SET company_id = (SELECT id FROM companies WHERE slug = 'yulcom') "
            "WHERE company_id IS NULL"
        )
```

Add at the very top of `downgrade()` — before every other line already in that function (this is migration `0013`'s own `downgrade()`; do not confuse with `recipients.country_id`, which belongs to migration `0003` and is untouched here):

```python
    op.drop_constraint("fk_recipients_company_id", "recipients", type_="foreignkey")
    op.drop_column("recipients", "company_id")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. Verify:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT company_id, COUNT(*) FROM recipients GROUP BY company_id;"`
Expected: all rows show the YULCOM company id (no NULLs).

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add Recipient.company_id, backfill existing recipients to YULCOM"
```

---

## Task 7: `User.company_id` and role rename (`admin`→`company_admin`, `viewer`→`company_viewer`)

**Files:**
- Modify: `src/tenderai_bf/models.py:291-310` (the `User` class)
- Modify: `alembic/versions/0013_add_companies.py`
- Modify: `tests/test_company_store.py`

**Interfaces:**
- Consumes: `Company` (Task 1).
- Produces: `User.company_id: int | None` (null only for `super_admin`); `User.role` values become `super_admin` | `company_admin` | `company_viewer`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_company_store.py`:

```python
def test_user_has_company_id_column(db):
    engine = db.get_bind()
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert "company_id" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Add the column to `User`**

In `src/tenderai_bf/models.py`, find the `User` class (around line 291-310). Modify the role comment and add the new column after `country_id` (around line 303):

```python
    role = Column(String(15), nullable=False, default="company_viewer")  # super_admin | company_admin | company_viewer
    is_active = Column(Boolean, nullable=False, default=True)
    password_reset_required = Column(Boolean, nullable=False, default=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
```

Add to the relationships block (near `country = relationship("Country", foreign_keys=[country_id])`):

```python
    company = relationship("Company", foreign_keys=[company_id])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_company_store.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Extend the migration — column + backfill + role rename**

Append to `alembic/versions/0013_add_companies.py`, inside `upgrade()`:

```python
    # 12. users.company_id — backfilled to YULCOM
    if _table_exists(bind, "users"):
        if not _column_exists(bind, "users", "company_id"):
            op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_users_company_id", "users", "companies", ["company_id"], ["id"]
            )
        op.execute(
            "UPDATE users SET company_id = (SELECT id FROM companies WHERE slug = 'yulcom') "
            "WHERE company_id IS NULL AND role != 'super_admin'"
        )

        # 13. Role rename: admin -> company_admin, viewer -> company_viewer (idempotent)
        op.execute("UPDATE users SET role = 'company_admin' WHERE role = 'admin'")
        op.execute("UPDATE users SET role = 'company_viewer' WHERE role = 'viewer'")
```

Add to `downgrade()` (before the `companies` table drop, reversing the rename first):

```python
    op.execute("UPDATE users SET role = 'viewer' WHERE role = 'company_viewer'")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'company_admin'")
    op.drop_constraint("fk_users_company_id", "users", type_="foreignkey")
    op.drop_column("users", "company_id")
```

- [ ] **Step 6: Run the migration against the local dev database**

Run: `docker compose exec api alembic upgrade head`
Expected: no errors. Verify:
`docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "SELECT username, role, company_id FROM users;"`
Expected: `super_admin` rows have `company_id = NULL`; every `company_admin`/`company_viewer` row has the YULCOM company id; no row still says `admin` or `viewer`.

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/models.py alembic/versions/0013_add_companies.py tests/test_company_store.py
git commit -m "feat(models): add User.company_id, rename roles to company_admin/company_viewer"
```

---

## Task 8: `CompanyStore` — data access layer

**Files:**
- Create: `src/tenderai_bf/company_store.py`
- Create: `tests/test_company_store_methods.py`

**Interfaces:**
- Consumes: `Company`, `CompanySettings`, `AppSettings` (all from earlier tasks / existing).
- Produces: `CompanyStore` class with static methods `get_section`, `put_section`, `get_all`, `get_all_with_fallback`, `seed_from_global` — identical signatures to `CountryStore` (`src/tenderai_bf/country_store.py`), consumed by Plan #2's `company_cfg()` accessor.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_company_store_methods.py`:

```python
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.db import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_company_store_get_section_returns_none_when_absent(db):
    from tenderai_bf.company_store import CompanyStore
    from tenderai_bf.models import Company

    company = Company(name="Test", slug="test-co")
    db.add(company)
    db.commit()
    assert CompanyStore.get_section(db, company.id, "classification") is None


def test_company_store_put_and_get_section(db):
    from tenderai_bf.company_store import CompanyStore
    from tenderai_bf.models import Company

    company = Company(name="Test", slug="test-co2")
    db.add(company)
    db.commit()
    CompanyStore.put_section(
        db, company.id, "classification", {"min_relevance_score": 0.6}, updated_by="test"
    )
    result = CompanyStore.get_section(db, company.id, "classification")
    assert result == {"min_relevance_score": 0.6}


def test_company_store_get_all_with_fallback_uses_global_for_missing(db):
    from tenderai_bf.company_store import CompanyStore
    from tenderai_bf.models import AppSettings, Company

    db.add(
        AppSettings(
            section="email",
            data={"subject_prefix": "TenderAI"},
            updated_by="test",
        )
    )
    db.commit()
    company = Company(name="New", slug="new-co")
    db.add(company)
    db.commit()
    result = CompanyStore.get_all_with_fallback(db, company.id)
    assert result["email"]["subject_prefix"] == "TenderAI"


def test_company_store_get_all_with_fallback_company_overrides_global(db):
    from tenderai_bf.company_store import CompanyStore
    from tenderai_bf.models import AppSettings, Company

    db.add(
        AppSettings(
            section="email",
            data={"subject_prefix": "TenderAI"},
            updated_by="test",
        )
    )
    db.commit()
    company = Company(name="Override", slug="override-co")
    db.add(company)
    db.commit()
    CompanyStore.put_section(
        db,
        company.id,
        "email",
        {"subject_prefix": "[ACME]"},
        updated_by="test",
    )
    result = CompanyStore.get_all_with_fallback(db, company.id)
    assert result["email"]["subject_prefix"] == "[ACME]"


def test_company_store_seed_from_global_copies_all_sections(db):
    from tenderai_bf.company_store import CompanyStore
    from tenderai_bf.models import AppSettings, Company

    db.add(
        AppSettings(section="classification", data={"min_relevance_score": 0.65}, updated_by="test")
    )
    db.add(AppSettings(section="scheduler", data={"cron_schedule": "0 7 * * *"}, updated_by="test"))
    db.commit()
    company = Company(name="Seed", slug="seed-co")
    db.add(company)
    db.commit()
    seeded = CompanyStore.seed_from_global(db, company.id)
    assert set(seeded) == {"classification", "scheduler"}
    assert CompanyStore.get_section(db, company.id, "classification") == {
        "min_relevance_score": 0.65
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_company_store_methods.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'tenderai_bf.company_store'`

- [ ] **Step 3: Write `CompanyStore`**

Create `src/tenderai_bf/company_store.py`:

```python
"""Per-company DB-backed settings store. One row per (company_id, section) in company_settings."""


from sqlalchemy.orm import Session

from .models import AppSettings, CompanySettings

MUTABLE_SECTIONS = frozenset({"classification", "scheduler", "email"})


class CompanyStore:
    @staticmethod
    def get_section(db: Session, company_id: int, section: str) -> dict | None:
        row = (
            db.query(CompanySettings)
            .filter(
                CompanySettings.company_id == company_id,
                CompanySettings.section == section,
            )
            .first()
        )
        return row.data if row else None

    @staticmethod
    def put_section(
        db: Session,
        company_id: int,
        section: str,
        data: dict,
        updated_by: str = "system",
    ) -> None:
        row = CompanySettings(
            company_id=company_id, section=section, data=data, updated_by=updated_by
        )
        db.merge(row)
        db.commit()

    @staticmethod
    def get_all(db: Session, company_id: int) -> dict[str, dict]:
        rows = (
            db.query(CompanySettings)
            .filter(CompanySettings.company_id == company_id)
            .all()
        )
        return {row.section: row.data for row in rows}

    @staticmethod
    def get_all_with_fallback(db: Session, company_id: int) -> dict[str, dict]:
        """Return per-company settings, falling back to global AppSettings for missing sections."""
        global_rows = db.query(AppSettings).all()
        merged = {row.section: row.data for row in global_rows}
        company_rows = (
            db.query(CompanySettings)
            .filter(CompanySettings.company_id == company_id)
            .all()
        )
        for row in company_rows:
            merged[row.section] = row.data
        return merged

    @staticmethod
    def seed_from_global(db: Session, company_id: int) -> list[str]:
        """Copy AppSettings rows into CompanySettings for a new company. Idempotent."""
        global_rows = db.query(AppSettings).all()
        seeded: list[str] = []
        for row in global_rows:
            exists = (
                db.query(CompanySettings)
                .filter(
                    CompanySettings.company_id == company_id,
                    CompanySettings.section == row.section,
                )
                .first()
            )
            if not exists:
                db.add(
                    CompanySettings(
                        company_id=company_id,
                        section=row.section,
                        data=row.data,
                        updated_by="seed",
                    )
                )
                seeded.append(row.section)
        db.commit()
        return seeded
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_company_store_methods.py -v --no-cov`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `poetry run pytest tests/ -v --no-cov`
Expected: all tests pass, including the pre-existing `tests/test_country_store.py` (unchanged) and every test added in Tasks 1-7.

- [ ] **Step 6: Commit**

```bash
git add src/tenderai_bf/company_store.py tests/test_company_store_methods.py
git commit -m "feat(company): add CompanyStore data access layer, mirrors CountryStore"
```

---

## Plan Completion Checklist

- [ ] All 8 tasks committed on `feature/multi-company`
- [ ] `docker compose exec api alembic upgrade head` runs clean from a fresh `0012` state
- [ ] `docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c "\dt company*"` shows all 4 new tables
- [ ] YULCOM company exists, subscribed to all active countries, with seeded `classification`/`scheduler` settings
- [ ] Every existing `Recipient`/`User` row has `company_id` set to YULCOM; every `Run` row has `run_type='harvest'`
- [ ] `poetry run pytest tests/ -v --no-cov` passes in full
- [ ] Ready to hand off to Plan #2 (pipeline harvest/delivery split), which consumes `CompanyStore`, `CompanyNoticeStatus`, and `Run.run_type`/`company_id` directly
