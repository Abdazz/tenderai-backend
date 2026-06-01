"""Tests for auth endpoints."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tenderai_bf.models import Base, User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_user_model_creation(db_session):
    user = User(
        id="test-uuid-1234",
        username="testuser",
        email="test@example.com",
        hashed_password="hashed",
        role="viewer",
    )
    db_session.add(user)
    db_session.commit()
    fetched = db_session.query(User).filter_by(username="testuser").first()
    assert fetched is not None
    assert fetched.role == "viewer"
    assert fetched.is_active is True
    assert fetched.password_reset_required is True


def test_user_role_admin(db_session):
    user = User(
        id="test-uuid-5678",
        username="adminuser",
        email="admin@example.com",
        hashed_password="hashed",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    fetched = db_session.query(User).filter_by(username="adminuser").first()
    assert fetched.role == "admin"
