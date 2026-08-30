"""Tests for company_id scoping added to recipients/runs/users, and removal
of the YULCOM-hardcoded stopgaps."""
import uuid
from unittest.mock import patch

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
            Recipient(
                email="a@a.com", group="to", enabled=True, company_id=company_a.id
            ),
            Recipient(
                email="b@b.com", group="to", enabled=True, company_id=company_b.id
            ),
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


@patch("tenderai_bf.agents.get_pipeline")
def test_super_admin_manual_trigger_defaults_to_yulcom(
    mock_get_pipeline, client, db_session, monkeypatch
):
    """The exact regression this task must not reintroduce: today's live
    admin account is super_admin, and clicking "Lancer maintenant" must
    keep delivering to YULCOM by default when no company_id is given.

    get_pipeline() (the harvest step) is patched here too, not just the
    delivery pipeline's run — countries.py's background _run() calls
    get_pipeline().run(...) FIRST, unpatched, and since TestClient executes
    background tasks synchronously within the request/response cycle, an
    unpatched get_pipeline() would run a real (network-touching) harvest
    pipeline during this test. See test_countries_run_trigger.py for the
    same pattern."""
    from unittest.mock import MagicMock

    mock_harvest_pipeline = MagicMock()
    mock_harvest_pipeline.run.return_value = MagicMock(error_occurred=False)
    mock_get_pipeline.return_value = mock_harvest_pipeline

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


def test_company_admin_cannot_trigger_delivery_for_another_company(client, db_session):
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
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="delivery",
                company_id=company_a.id,
            ),
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="delivery",
                company_id=company_b.id,
            ),
            Run(
                id=str(uuid.uuid4()),
                status="completed",
                run_type="harvest",
                company_id=None,
            ),
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
    admin_body = admin_resp.json()
    assert admin_body["total"] == 1
    assert admin_body["runs"][0]["run_type"] == "delivery"

    root_resp = client.get(
        "/api/v1/runs", headers={"Authorization": f"Bearer {root_token}"}
    )
    assert root_resp.status_code == 200
    root_body = root_resp.json()
    assert root_body["total"] == 3
    assert {r["run_type"] for r in root_body["runs"]} == {"delivery", "harvest"}


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
    other_company = Company(
        name="Trigger Other Co", slug="trigger-other-co", active=True
    )
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


def _seed_two_companies_with_recipient(db_session):
    """Shared setup for the recipients-by-ID scoping tests below: two
    companies, a company_admin for each, and a recipient owned by company B."""
    company_a = Company(name="Recip Scope Co A", slug="recip-scope-co-a", active=True)
    company_b = Company(name="Recip Scope Co B", slug="recip-scope-co-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    recipient_b = Recipient(
        email="b-owned@test.com", group="to", enabled=True, company_id=company_b.id
    )
    db_session.add(recipient_b)

    admin_a = User(
        id=str(uuid.uuid4()),
        username="recip_admin_a",
        email="recip_admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    viewer_b = User(
        id=str(uuid.uuid4()),
        username="recip_viewer_b",
        email="recip_viewer_b@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_viewer",
        company_id=company_b.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([admin_a, viewer_b])
    db_session.commit()
    db_session.refresh(recipient_b)

    return company_a, company_b, recipient_b


def test_company_admin_cannot_get_update_delete_other_companys_recipient(
    client, db_session
):
    """C2: get/update/delete by ID had zero company scoping — a company_admin
    of company A could GET/PUT/DELETE company B's recipient by ID."""
    _company_a, _company_b, recipient_b = _seed_two_companies_with_recipient(db_session)
    token_a = _login(client, "recip_admin_a", "pass12345")
    headers = {"Authorization": f"Bearer {token_a}"}

    get_resp = client.get(f"/api/v1/recipients/{recipient_b.id}", headers=headers)
    assert get_resp.status_code == 403

    put_resp = client.put(
        f"/api/v1/recipients/{recipient_b.id}",
        json={"name": "Hijacked"},
        headers=headers,
    )
    assert put_resp.status_code == 403

    delete_resp = client.delete(f"/api/v1/recipients/{recipient_b.id}", headers=headers)
    assert delete_resp.status_code == 403


def test_company_viewer_cannot_update_or_delete_own_recipient_but_can_get(
    client, db_session
):
    """C2: company_viewer is explicitly read-only — it must 403 on PUT/DELETE
    even for its own company's recipient, but GET must still succeed (200)."""
    _company_a, _company_b, recipient_b = _seed_two_companies_with_recipient(db_session)
    token_viewer = _login(client, "recip_viewer_b", "pass12345")
    headers = {"Authorization": f"Bearer {token_viewer}"}

    get_resp = client.get(f"/api/v1/recipients/{recipient_b.id}", headers=headers)
    assert get_resp.status_code == 200

    put_resp = client.put(
        f"/api/v1/recipients/{recipient_b.id}",
        json={"name": "Should Not Work"},
        headers=headers,
    )
    assert put_resp.status_code == 403

    delete_resp = client.delete(f"/api/v1/recipients/{recipient_b.id}", headers=headers)
    assert delete_resp.status_code == 403


def test_super_admin_can_create_recipient_for_explicit_non_yulcom_company(
    client, db_session
):
    """I2: RecipientCreate previously had no company_id param, so a
    super_admin could never create a recipient for any company except
    YULCOM (the hardcoded fallback) via the API."""
    yulcom = Company(name="YULCOM Technologies", slug="yulcom", active=True)
    other = Company(name="Some Other Co", slug="some-other-co", active=True)
    db_session.add_all([yulcom, other])
    db_session.commit()

    root = User(
        id=str(uuid.uuid4()),
        username="recip_root",
        email="recip_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(root)
    db_session.commit()
    token = _login(client, "recip_root", "rootpass123")

    resp = client.post(
        "/api/v1/recipients",
        json={
            "email": "someone@some-other-co.com",
            "name": "Someone",
            "group": "to",
            "enabled": True,
            "company_id": other.id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] == other.id


def test_anonymous_request_gets_401_not_unfiltered_data(client, db_session):
    """C3: list_runs/list_reports previously used the optional-auth
    CurrentUser type with a `if current_user and ...` guard, so a caller
    presenting no Authorization header at all skipped the company filter
    entirely and got every company's runs/reports back. An anonymous
    request must now 401, not 200-with-all-data."""
    from tenderai_bf.models import Run

    db_session.add(
        Run(
            id=str(uuid.uuid4()),
            status="completed",
            run_type="delivery",
            company_id=None,
            report_url="http://minio/anon-report.docx",
        )
    )
    db_session.commit()

    runs_resp = client.get("/api/v1/runs")
    assert runs_resp.status_code == 401

    reports_resp = client.get("/api/v1/reports")
    assert reports_resp.status_code == 401


def test_company_viewer_cannot_delete_run(client, db_session):
    """I4: delete_run had no company/role scoping at all — a company_viewer
    of company A could delete company B's (or anyone's) run row."""
    from tenderai_bf.models import Run

    company_a = Company(name="Del Run Co A", slug="del-run-co-a", active=True)
    company_b = Company(name="Del Run Co B", slug="del-run-co-b", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    run_b = Run(
        id=str(uuid.uuid4()),
        status="completed",
        run_type="delivery",
        company_id=company_b.id,
    )
    db_session.add(run_b)

    viewer_a = User(
        id=str(uuid.uuid4()),
        username="del_run_viewer_a",
        email="del_run_viewer_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_viewer",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(viewer_a)
    db_session.commit()
    token = _login(client, "del_run_viewer_a", "pass12345")

    resp = client.delete(
        f"/api/v1/runs/{run_b.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_company_admin_cannot_delete_other_companys_run(client, db_session):
    """I4: symmetric to the viewer case — a company_admin of company A
    cannot delete company B's run even though company_admin can write."""
    from tenderai_bf.models import Run

    company_a = Company(name="Del Run Co A2", slug="del-run-co-a2", active=True)
    company_b = Company(name="Del Run Co B2", slug="del-run-co-b2", active=True)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    run_b = Run(
        id=str(uuid.uuid4()),
        status="completed",
        run_type="delivery",
        company_id=company_b.id,
    )
    db_session.add(run_b)

    admin_a = User(
        id=str(uuid.uuid4()),
        username="del_run_admin_a",
        email="del_run_admin_a@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin_a)
    db_session.commit()
    token = _login(client, "del_run_admin_a", "pass12345")

    resp = client.delete(
        f"/api/v1/runs/{run_b.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_company_admin_can_delete_own_companys_run(client, db_session):
    """I4: the positive case — company_admin CAN delete a run belonging to
    their own company."""
    from tenderai_bf.models import Run

    company_a = Company(name="Del Run Co A3", slug="del-run-co-a3", active=True)
    db_session.add(company_a)
    db_session.commit()

    run_a = Run(
        id=str(uuid.uuid4()),
        status="completed",
        run_type="delivery",
        company_id=company_a.id,
    )
    db_session.add(run_a)

    admin_a = User(
        id=str(uuid.uuid4()),
        username="del_run_admin_a3",
        email="del_run_admin_a3@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company_a.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin_a)
    db_session.commit()
    token = _login(client, "del_run_admin_a3", "pass12345")

    resp = client.delete(
        f"/api/v1/runs/{run_a.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 204


def test_update_user_rejects_company_role_without_company_id(client, db_session):
    """I5: update_user didn't re-validate the role/company_id pairing that
    create_user enforces — a PATCH setting role=company_admin on a user
    whose company_id is currently NULL used to succeed, producing an
    orphaned company_admin."""
    root = User(
        id=str(uuid.uuid4()),
        username="update_role_root",
        email="update_role_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    orphan_candidate = User(
        id=str(uuid.uuid4()),
        username="orphan_candidate",
        email="orphan_candidate@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([root, orphan_candidate])
    db_session.commit()
    token = _login(client, "update_role_root", "rootpass123")

    resp = client.patch(
        f"/api/v1/users/{orphan_candidate.id}",
        json={"role": "company_admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_update_user_promoting_to_super_admin_clears_company_and_country(
    client, db_session
):
    """I5: symmetrically, promoting a user to super_admin via PATCH must
    clear their existing company_id/country_id, not leave them stale."""
    from tenderai_bf.models import Country

    company = Company(name="Promote Co", slug="promote-co", active=True)
    country = Country(name="Burkina Faso", code="BF", locale="fr")
    db_session.add_all([company, country])
    db_session.commit()

    root = User(
        id=str(uuid.uuid4()),
        username="promote_root",
        email="promote_root@test.com",
        hashed_password=get_password_hash("rootpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    to_promote = User(
        id=str(uuid.uuid4()),
        username="to_promote",
        email="to_promote@test.com",
        hashed_password=get_password_hash("pass12345"),
        role="company_admin",
        company_id=company.id,
        country_id=country.id,
        is_active=True,
        password_reset_required=False,
    )
    db_session.add_all([root, to_promote])
    db_session.commit()
    token = _login(client, "promote_root", "rootpass123")

    resp = client.patch(
        f"/api/v1/users/{to_promote.id}",
        json={"role": "super_admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["company_id"] is None
    assert resp.json()["country_id"] is None
