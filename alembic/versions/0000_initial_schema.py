"""initial_schema

Revision ID: 0000
Revises:
Create Date: 2026-06-12

Creates the core tables that pre-date Alembic (sources, runs, notices,
notice_urls, files, recipients). On existing databases these tables already
exist so every statement uses IF NOT EXISTS — the migration is idempotent.

Later migrations add columns / FKs on top of this baseline:
  0003 → adds country_id to sources, runs, recipients + creates countries
  0005 → backfills country_id nulls
  0006/0007 → seeds BF sources
"""

import sqlalchemy as sa
from alembic import op

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            base_url    VARCHAR(500) NOT NULL,
            list_url    VARCHAR(500) NOT NULL,
            parser_type VARCHAR(50)  NOT NULL DEFAULT 'html',
            rate_limit  VARCHAR(20)  NOT NULL DEFAULT '10/m',
            enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
            patterns    JSON,
            last_seen_at      TIMESTAMP,
            last_success_at   TIMESTAMP,
            last_error_at     TIMESTAMP,
            last_error_message TEXT,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sources_name    ON sources (name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sources_enabled ON sources (enabled)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id              VARCHAR(36) PRIMARY KEY,
            status          VARCHAR(40)  NOT NULL,
            started_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
            finished_at     TIMESTAMP,
            counts_json     JSON,
            error_message   TEXT,
            error_traceback TEXT,
            logs_url        VARCHAR(500),
            report_url      VARCHAR(500),
            triggered_by    VARCHAR(50)  NOT NULL DEFAULT 'scheduler',
            triggered_by_user VARCHAR(100)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_runs_id     ON runs (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_runs_status ON runs (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id                  VARCHAR(36) PRIMARY KEY,
            source_id           INTEGER     NOT NULL REFERENCES sources(id),
            run_id              VARCHAR(36) NOT NULL REFERENCES runs(id),
            title               VARCHAR(500) NOT NULL,
            ref_no              VARCHAR(100),
            entity              VARCHAR(300),
            category            VARCHAR(100),
            published_at        TIMESTAMP,
            deadline_at         TIMESTAMP,
            location            VARCHAR(200),
            budget_xof          FLOAT,
            currency            VARCHAR(10),
            description         TEXT,
            summary_fr          TEXT,
            summary_en          TEXT,
            relevance_score     FLOAT,
            is_relevant         BOOLEAN NOT NULL DEFAULT FALSE,
            classification_method VARCHAR(50),
            content_hash        VARCHAR(64) NOT NULL,
            is_duplicate        BOOLEAN NOT NULL DEFAULT FALSE,
            duplicate_of_id     VARCHAR(36) REFERENCES notices(id),
            url                 VARCHAR(1000) NOT NULL,
            created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_id              ON notices (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_source_id       ON notices (source_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_run_id          ON notices (run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_title           ON notices (title)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_ref_no          ON notices (ref_no)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_entity          ON notices (entity)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_content_hash    ON notices (content_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_is_relevant     ON notices (is_relevant)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notices_is_duplicate    ON notices (is_duplicate)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS notice_urls (
            id          SERIAL PRIMARY KEY,
            notice_id   VARCHAR(36) NOT NULL REFERENCES notices(id),
            url         VARCHAR(1000) NOT NULL,
            url_type    VARCHAR(50) NOT NULL DEFAULT 'source',
            description VARCHAR(200),
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_notice_urls_id        ON notice_urls (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notice_urls_notice_id ON notice_urls (notice_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id              VARCHAR(36) PRIMARY KEY,
            notice_id       VARCHAR(36) NOT NULL REFERENCES notices(id),
            filename        VARCHAR(255) NOT NULL,
            content_type    VARCHAR(100) NOT NULL,
            size_bytes      INTEGER,
            kind            VARCHAR(50)  NOT NULL,
            description     VARCHAR(200),
            storage_key     VARCHAR(500) NOT NULL,
            storage_url     VARCHAR(1000),
            checksum        VARCHAR(64),
            processed       BOOLEAN NOT NULL DEFAULT FALSE,
            ocr_text        TEXT,
            processing_error TEXT,
            source_url      VARCHAR(1000),
            created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_files_id        ON files (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_files_notice_id ON files (notice_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_files_kind      ON files (kind)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS recipients (
            id         SERIAL PRIMARY KEY,
            email      VARCHAR(255) NOT NULL,
            name       VARCHAR(255),
            is_active  BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recipients_id ON recipients (id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recipients")
    op.execute("DROP TABLE IF EXISTS files")
    op.execute("DROP TABLE IF EXISTS notice_urls")
    op.execute("DROP TABLE IF EXISTS notices")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS sources")
