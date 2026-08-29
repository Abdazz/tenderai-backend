"""Tests for company_id scoping added to recipients/runs/users, and removal
of the YULCOM-hardcoded stopgaps."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, Company, Country, Recipient, User


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)  # noqa: N806 — SQLAlchemy idiom for a session factory
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    resp = client.post(
        "/api/v1/admin/login/simple", json={"username": username, "password": password}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_recipient_created_by_company_admin_gets_own_company_id(client, db_session):
    company = Company(name="Test Co", slug="test-co", active=True)
    country = Country(name="Canada", code="CA", locale="fr")
    db_session.add_all([company, country])
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="testco_admin",
        email="testco_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()

    token = _login(client, "testco_admin", "pass12345")

    resp = client.post(
        "/api/v1/recipients",
        json={
            "email": "someone@test-co.com",
            "name": "Someone",
            "group": "to",
            "enabled": True,
            "country_id": country.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] == company.id  # not hardcoded to YULCOM


def test_recipients_list_filtered_to_own_company(client, db_session):
    company_a = Company(name="Company A", slug="company-a", active=True)
    company_b = Company(name="Company B", slug="company-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    db_session.add_all(
        [
            Recipient(email="a@a.com", group="to", enabled=True, company_id=company_a.id),
            Recipient(email="b@b.com", group="to", enabled=True, company_id=company_b.id),
        ]
    )
    admin_a = User(
        id=str(uuid.uuid4()),
        username="admin_a",
        email="admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin_a)
    db_session.commit()

    token = _login(client, "admin_a", "pass12345")

    resp = client.get(
        "/api/v1/recipients", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    emails = [r["email"] for r in resp.json()["recipients"]]
    assert emails == ["a@a.com"]


def test_create_company_admin_user_requires_company_id(client, db_session):
    root = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(root)
    db_session.commit()
    token = _login(client, "root", "rootpass123")

    resp = client.post(
        "/api/v1/users",
        json={
            "username": "newcompanyadmin",
            "email": "newcompanyadmin@test.com",
            "role": "company_admin",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_super_admin_manual_trigger_defaults_to_yulcom(client, db_session, monkeypatch):
    """The exact regression this task must not reintroduce: today's live
    admin account is super_admin, and clicking "Lancer maintenant" must
    keep delivering to YULCOM by default when no company_id is given."""
    from tenderai_bf.models import Country

    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    country = Country(name="Burkina Faso", code="BF", locale="fr")
    db_session.add_all([yulcom, country])
    db_session.commit()

    root = User(
        id=str(uuid.uuid4()),
        username="root",
        email="root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(root)
    db_session.commit()
    token = _login(client, "root", "rootpass123")

    from unittest.mock import MagicMock

    from tenderai_bf.agents import get_delivery_pipeline

    fake_result = MagicMock(error_occurred=False, warnings=[])
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return fake_result

    monkeypatch.setattr(get_delivery_pipeline(), "run", fake_run)

    resp = client.post(
        f"/api/v1/admin/countries/{country.id}/run",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert resp.json()["company_id"] == yulcom.id


def test_company_admin_cannot_trigger_delivery_for_another_company(
    client, db_session
):
    from tenderai_bf.models import Country

    own_company = Company(name="Own Co", slug="own-co", active=True)
    other_company = Company(name="Other Co", slug="other-co", active=True)
    country = Country(name="Burkina Faso", code="BF", locale="fr")
    db_session.add_all([own_company, other_company, country])
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="own_admin",
        email="own_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=own_company.id,
        country_id=country.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()
    token = _login(client, "own_admin", "pass12345")

    resp = client.post(
        f"/api/v1/admin/countries/{country.id}/run?company_id={other_company.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_source_write_endpoints_require_super_admin(client, db_session):
    """sources.py's new read-only enforcement: company_admin/company_viewer
    cannot create/update/delete sources; super_admin is not blocked."""
    from tenderai_bf.models import Source

    source = Source(
        name="Existing Source",
        base_url="https://example.com",
        list_url="https://example.com/list",
    )
    db_session.add(source)
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="src_admin",
        email="src_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        is_active=True,
        password_reset_required=False,
    )
    root = User(
        id=str(uuid.uuid4()),
        username="src_root",
        email="src_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([admin, root])
    db_session.commit()

    admin_token = _login(client, "src_admin", "pass12345")
    root_token = _login(client, "src_root", "rootpass123")

    new_source_payload = {
        "name": "New Source",
        "base_url": "https://example.com",
        "list_url": "https://example.com/list",
    }

    create_resp = client.post(
        "/api/v1/sources",
        json=new_source_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 403

    update_resp = client.put(
        f"/api/v1/sources/{source.id}",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert update_resp.status_code == 403

    delete_resp = client.delete(
        f"/api/v1/sources/{source.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_resp.status_code == 403

    # super_admin is not blocked by this guard
    root_create_resp = client.post(
        "/api/v1/sources",
        json=new_source_payload,
        headers={"Authorization": f"Bearer {root_token}"},
    )
    assert root_create_resp.status_code == 201


def test_list_runs_filtered_to_own_company(client, db_session):
    """runs.py's list_runs: company_admin sees only run_type='delivery' runs
    for their own company; super_admin sees everything."""
    from tenderai_bf.models import Run

    company_a = Company(name="Runs Company A", slug="runs-company-a", active=True)
    company_b = Company(name="Runs Company B", slug="runs-company-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    db_session.add_all(
        [
            Run(id=str(uuid.uuid4()), status="completed", run_type="delivery", company_id=company_a.id),
            Run(id=str(uuid.uuid4()), status="completed", run_type="delivery", company_id=company_b.id),
            Run(id=str(uuid.uuid4()), status="completed", run_type="harvest", company_id=None),
        ]
    )
    admin_a = User(
        id=str(uuid.uuid4()),
        username="runs_admin_a",
        email="runs_admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    root = User(
        id=str(uuid.uuid4()),
        username="runs_root",
        email="runs_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([admin_a, root])
    db_session.commit()

    admin_token = _login(client, "runs_admin_a", "pass12345")
    root_token = _login(client, "runs_root", "rootpass123")

    admin_resp = client.get(
        "/api/v1/runs", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_resp.status_code == 200
    assert admin_resp.json()["total"] == 1

    root_resp = client.get(
        "/api/v1/runs", headers={"Authorization": f"Bearer {root_token}"}
    )
    assert root_resp.status_code == 200
    assert root_resp.json()["total"] == 3


def test_list_reports_filtered_to_own_company(client, db_session):
    """reports.py's list_reports: company_admin sees only their own
    company's delivery reports; super_admin sees everything."""
    from tenderai_bf.models import Run

    company_a = Company(name="Reports Company A", slug="reports-company-a", active=True)
    company_b = Company(name="Reports Company B", slug="reports-company-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    db_session.add_all(
        [
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="delivery",
                company_id=company_a.id,
                report_url="http://minio/report-a.docx",
            ),
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="delivery",
                company_id=company_b.id,
                report_url="http://minio/report-b.docx",
            ),
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="harvest",
                company_id=None,
                report_url="http://minio/report-harvest.docx",
            ),
        ]
    )
    admin_a = User(
        id=str(uuid.uuid4()),
        username="reports_admin_a",
        email="reports_admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    root = User(
        id=str(uuid.uuid4()),
        username="reports_root",
        email="reports_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([admin_a, root])
    db_session.commit()

    admin_token = _login(client, "reports_admin_a", "pass12345")
    root_token = _login(client, "reports_root", "rootpass123")

    admin_resp = client.get(
        "/api/v1/reports", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_resp.status_code == 200
    assert admin_resp.json()["total"] == 1

    root_resp = client.get(
        "/api/v1/reports", headers={"Authorization": f"Bearer {root_token}"}
    )
    assert root_resp.status_code == 200
    assert root_resp.json()["total"] == 3


def test_company_admin_cannot_trigger_runs_endpoint_for_another_company(
    client, db_session
):
    """runs.py's POST /trigger: the symmetric guard to the countries.py test
    above — a company_admin requesting delivery for a company_id that isn't
    their own gets 403."""
    own_company = Company(name="Trigger Own Co", slug="trigger-own-co", active=True)
    other_company = Company(name="Trigger Other Co", slug="trigger-other-co", active=True)
    db_session.add_all([own_company, other_company])
    db_session.commit()

    admin = User(
        id=str(uuid.uuid4()),
        username="trigger_admin",
        email="trigger_admin@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=own_company.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()
    token = _login(client, "trigger_admin", "pass12345")

    resp = client.post(
        "/api/v1/runs/trigger",
        json={"company_id": other_company.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
