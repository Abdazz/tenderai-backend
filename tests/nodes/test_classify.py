"""Test classification node independently."""

import sys

sys.path.insert(0, "/app/src")

from tenderai_bf.agents.nodes.classify import classify_with_keywords, classify_with_llm

# Sample tender items to classify
sample_items = [
    {
        "id": "test_1",
        "title": "Acquisition de serveurs et équipements réseau",
        "description": "Fourniture de 10 serveurs Dell PowerEdge, switches Cisco et équipements réseau pour datacenter",
        "category": "IT Hardware",
        "entity": "Ministère de la Santé",
        "keywords": ["serveur", "réseau", "datacenter", "informatique"],
    },
    {
        "id": "test_2",
        "title": "Construction de routes rurales",
        "description": "Travaux de construction de 50km de routes en zone rurale, région du Sahel",
        "category": "BTP",
        "entity": "Ministère des Infrastructures",
        "keywords": ["construction", "routes", "travaux publics"],
    },
    {
        "id": "test_3",
        "title": "Développement application mobile de santé",
        "description": "Conception et développement d'une application mobile pour suivi médical des patients",
        "category": "IT Services",
        "entity": "CHU de Ouagadougou",
        "keywords": ["mobile", "application", "développement", "santé"],
    },
]


_MOCK_COUNTRY_CONFIG = {
    "llm": {
        "provider": "groq",
        "groq_model": "llama-3.3-70b-versatile",
        "openai_model": "gpt-4o",
        "ollama_model": "llama3",
        "ollama_base_url": "",
        "temperature": 0.1,
        "max_tokens": 2000,
        "timeout": 60,
    },
}

_MOCK_COMPANY_CONFIG = {
    "classification": {
        "min_relevance_score": 0.3,
        "relevant_keywords": {
            "it_services": [
                "informatique",
                "logiciel",
                "réseau",
                "serveur",
                "ordinateur",
                "internet",
                "site web",
                "application",
                "base de données",
                "cybersécurité",
                "cloud",
                "données",
                "numérique",
                "digital",
                "ERP",
                "CRM",
                "SIG",
                "GIS",
                "télécommunication",
                "fibre optique",
            ],
        },
    },
}


def test_keyword_classification():
    """Test keyword-based classification."""

    print("=" * 80)
    print("TEST: Classification par mots-clés")
    print("=" * 80)

    # Create mock state
    class MockState:
        def __init__(self):
            self.items_parsed = sample_items
            self.relevant_items = []
            self.run_id = "test_keywords"
            self.country_id = 0
            self.country_config = _MOCK_COUNTRY_CONFIG
            self.company_id = 0
            self.company_config = _MOCK_COMPANY_CONFIG

        def update_stats(self, **kwargs):
            print(f"\n📊 Stats updated: {kwargs}")

    state = MockState()

    print(f"\n📋 Items à classifier: {len(state.items_parsed)}")
    for item in state.items_parsed:
        print(f"  - {item['id']}: {item['title'][:60]}...")

    print("\n🔄 Classification en cours...")
    result = classify_with_keywords(state)

    print("\n✅ Classification terminée")
    print(f"   Items pertinents: {len(result.relevant_items)}")

    if result.relevant_items:
        print("\n📌 Items pertinents :")
        for item in result.relevant_items:
            print(f"  - {item['id']}: {item['title'][:60]}")
            print(f"    Score: {item.get('relevance_score', 0):.2f}")
            print(f"    Méthode: {item.get('classification_method', 'N/A')}")

    print("\n" + "=" * 80)
    return result


def test_llm_classification():
    """Test LLM-based classification."""

    print("\n" + "=" * 80)
    print("TEST: Classification par LLM")
    print("=" * 80)

    # Create mock state
    class MockState:
        def __init__(self):
            self.items_parsed = sample_items
            self.relevant_items = []
            self.unique_items = []
            self.run_id = "test_llm"
            self.country_id = 0
            self.country_config = _MOCK_COUNTRY_CONFIG
            self.company_id = 0
            self.company_config = _MOCK_COMPANY_CONFIG

        def update_stats(self, **kwargs):
            print(f"\n📊 Stats updated: {kwargs}")

    state = MockState()

    print(f"\n📋 Items à classifier: {len(state.items_parsed)}")
    for item in state.items_parsed:
        print(f"  - {item['id']}: {item['title'][:60]}...")

    print("\n🔄 Classification LLM en cours...")
    result = classify_with_llm(state)

    print("\n✅ Classification terminée")
    print(f"   Items pertinents: {len(result.relevant_items)}")

    if result.relevant_items:
        print("\n📌 Items pertinents :")
        for item in result.relevant_items:
            print(f"  - {item['id']}: {item['title'][:60]}")
            print(f"    Score: {item.get('relevance_score', 0):.2f}")

    print("\n" + "=" * 80)
    return result


if __name__ == "__main__":
    # Test both methods
    print("\n🧪 Testing Classification Methods\n")

    print("\n1️⃣ Test avec mots-clés")
    test_keyword_classification()

    print("\n\n2️⃣ Test avec LLM")
    test_llm_classification()


# ---------------------------------------------------------------------------
# DB-first company_cfg() tests — use TenderAIState, not MockState
# ---------------------------------------------------------------------------

import os  # noqa: E402 — grouped with the env var setup it configures below, not with the file's top-of-file imports

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.agents.graph import TenderAIState  # noqa: E402

COMPANY_CONFIG_CLASSIFY = {
    "classification": {
        "min_relevance_score": 0.3,
        "relevant_keywords": {
            "it_services": ["informatique", "logiciel", "serveur", "réseau"],
        },
    },
}

COUNTRY_CONFIG_CLASSIFY = {
    "llm": {
        "provider": "groq",
        "groq_model": "llama-3.3-70b-versatile",
        "openai_model": "gpt-4o",
        "ollama_model": "llama3",
        "ollama_base_url": "",
        "temperature": 0.1,
        "max_tokens": 2000,
        "timeout": 60,
    },
}


def test_classify_with_keywords_uses_company_config():
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {
                "id": "t1",
                "title": "Acquisition de serveurs et réseau",
                "description": "Fourniture de serveurs",
                "category": "IT",
                "entity": "Ministère",
                "keywords": [],
            },
            {
                "id": "t2",
                "title": "Construction de routes rurales",
                "description": "Travaux BTP",
                "category": "BTP",
                "entity": "Mairie",
                "keywords": [],
            },
        ],
    )
    result = classify_with_keywords(state)
    relevant_ids = [i["id"] for i in result.relevant_items]
    assert "t1" in relevant_ids
    assert "t2" not in relevant_ids


def test_classify_fails_hard_if_company_config_missing():
    import pytest

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config={},
        items_parsed=[
            {
                "id": "t1",
                "title": "test",
                "description": "x",
                "category": "IT",
                "entity": "X",
                "keywords": [],
            }
        ],
    )
    with pytest.raises(RuntimeError, match="Missing DB config: company_id=1"):
        classify_with_keywords(state)


def test_classify_no_longer_reads_classification_embedded():
    """Neutralization: an item with classification_embedded=True must go
    through the normal keyword path, not bypass it."""
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {
                "id": "t3",
                "title": "Construction de routes rurales",
                "description": "Travaux BTP, aucun rapport avec les technologies",
                "category": "BTP",
                "entity": "Mairie",
                "keywords": [],
                # Pre-neutralization, this field would have made classify_node
                # pass the item through as relevant unconditionally. It must
                # now be ignored entirely.
                "classification_embedded": True,
                "is_relevant": True,
                "relevance_score": 0.9,
            },
        ],
    )
    result = classify_with_keywords(state)
    relevant_ids = [i["id"] for i in result.relevant_items]
    assert "t3" not in relevant_ids
