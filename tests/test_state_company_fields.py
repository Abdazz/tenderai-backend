import os

os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

# Import below must follow the env var setup above (config validates on import).
from tenderai_bf.agents.graph import TenderAIState  # noqa: E402


def test_state_defaults_company_fields():
    state = TenderAIState()
    assert state.company_id == 0
    assert state.company_config == {}


def test_state_accepts_company_fields():
    state = TenderAIState(company_id=3, company_config={"classification": {}})
    assert state.company_id == 3
    assert state.company_config == {"classification": {}}
