"""Tests for standalone data-migration behavior not covered by model/API tests."""
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tenderai.models import Base, User


def test_role_rename_migration_logic():
    """Simulates migration 0014's UPDATE statements directly against a fresh
    in-memory DB seeded with legacy role values, since running real Alembic
    migrations against SQLite in test isn't set up in this repo (Postgres-only
    migrations use op.execute with Postgres-flavored SQL elsewhere)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    admin_user = User(
        id=str(uuid.uuid4()),
        username="legacy_admin",
        email="legacy_admin@test.com",
        hashed_password="hashed",
        role="admin",
    )
    viewer_user = User(
        id=str(uuid.uuid4()),
        username="legacy_viewer",
        email="legacy_viewer@test.com",
        hashed_password="hashed",
        role="viewer",
    )
    super_admin_user = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password="hashed",
        role="super_admin",
    )
    session.add_all([admin_user, viewer_user, super_admin_user])
    session.commit()

    # Same UPDATE statements migration 0014 runs against Postgres.
    session.execute(
        text("UPDATE users SET role = 'company_admin' WHERE role = 'admin'")
    )
    session.execute(
        text("UPDATE users SET role = 'company_viewer' WHERE role = 'viewer'")
    )
    session.commit()

    session.refresh(admin_user)
    session.refresh(viewer_user)
    session.refresh(super_admin_user)

    assert admin_user.role == "company_admin"
    assert viewer_user.role == "company_viewer"
    assert super_admin_user.role == "super_admin"  # unchanged

    session.close()
