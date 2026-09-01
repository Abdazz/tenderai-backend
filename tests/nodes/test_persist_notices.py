import hashlib
import os

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Imports below must follow the env var setup above (config validates on import).
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.persist_notices import persist_notices_node  # noqa: E402
from tenderai.db import Base  # noqa: E402
from tenderai.models import Country, Notice, Run, Source  # noqa: E402


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    country = Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True)
    source_a = Source(
        id=10,
        name="DGCMEF Burkina Faso",
        base_url="https://dgcmef.gov.bf",
        list_url="https://dgcmef.gov.bf/list",
        parser_type="html",
        enabled=True,
        country_id=1,
    )
    run = Run(id="run-1", status="running", triggered_by="test", country_id=1)
    session.add_all([country, source_a, run])
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session

            def __exit__(self, *a):
                pass

        return _Ctx()

    monkeypatch.setattr(
        "tenderai.agents.nodes.persist_notices.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_persist_notices_resolves_by_source_name(db_session):
    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[{"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1}],
        unique_items=[
            {
                "id": "item-1",
                "title": "Acquisition de serveurs",
                "url": "https://dgcmef.gov.bf/notice/1",
                "content_hash": _h("notice-1"),
                "source_name": "DGCMEF Burkina Faso",
                "entity": "Ministère X",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred

    notices = db_session.query(Notice).all()
    assert len(notices) == 1
    assert notices[0].source_id == 10
    assert notices[0].run_id == "run-1"
    assert notices[0].title == "Acquisition de serveurs"
    assert notices[0].is_relevant is False  # column default — harvest never sets this
    assert notices[0].relevance_score is None
    # RunStatistics must actually define these fields, or update_stats()
    # silently drops them (it only assigns attributes that already exist).
    assert result.stats.notices_persisted == 1
    assert result.stats.persist_time_seconds >= 0


def test_persist_notices_resolves_by_source_tag_substring(db_session):
    # Second source so tier 3's single-source-per-country fallback can't apply —
    # this test must genuinely exercise tier 2 (substring match on the "source"
    # tag), not fall through to tier 3.
    db_session.add(
        Source(
            id=11,
            name="UNGM",
            base_url="https://ungm.org",
            list_url="https://ungm.org/list",
            parser_type="html",
            enabled=True,
            country_id=1,
        )
    )
    db_session.commit()

    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[
            {"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1},
            {"id": 11, "name": "UNGM", "country_id": 1},
        ],
        unique_items=[
            {
                "id": "item-2",
                "title": "Fourniture d'équipements réseau",
                "url": "https://ungm.org/notice/2",
                "content_hash": _h("notice-2"),
                # No source_name — only a generic pathway tag. Substring-matches
                # exactly one of the two sources present ("ungm" in "ungm".lower()),
                # so this genuinely exercises tier 2, not tier 3.
                "source": "ungm",
                "entity": "Ministère Y",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred
    notices = db_session.query(Notice).all()
    assert len(notices) == 1
    assert notices[0].source_id == 11


def test_persist_notices_skips_unresolvable_source_with_warning(db_session):
    # Add a second source so the single-source fallback no longer applies.
    from tenderai.models import Source

    db_session.add(
        Source(
            id=11,
            name="UNGM",
            base_url="https://ungm.org",
            list_url="https://ungm.org/list",
            parser_type="html",
            enabled=True,
            country_id=1,
        )
    )
    db_session.commit()

    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[
            {"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1},
            {"id": 11, "name": "UNGM", "country_id": 1},
        ],
        unique_items=[
            {
                "id": "item-3",
                "title": "Some tender",
                "url": "https://example.com/notice/3",
                "content_hash": _h("notice-3"),
                # No source_name, no matching source tag, and now two possible
                # sources — must be skipped with a warning, not guessed.
                "source": "unknown_pathway",
                "entity": "Entity Z",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred
    notices = db_session.query(Notice).all()
    assert len(notices) == 0
    assert len(result.warnings) == 1
    assert result.warnings[0]["step"] == "persist_notices"
