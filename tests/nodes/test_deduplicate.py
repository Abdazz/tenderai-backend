"""Test deduplication node independently."""

import sys

sys.path.insert(0, "/app/src")

from tenderai.agents.nodes.deduplicate import check_duplicate_with_llm

# Sample tender pairs to test deduplication
test_pairs = [
    {
        "name": "Duplicates évidents (même référence)",
        "item1": {
            "id": "tender_1a",
            "title": "Acquisition de fournitures de bureau",
            "entity": "Ministère de l'Éducation",
            "reference": "AO-2025/001/MEN",
            "description": "Fourniture de matériel de bureau pour les écoles primaires",
            "deadline": "2025-02-15",
        },
        "item2": {
            "id": "tender_1b",
            "title": "Acquisition de fournitures de bureau",
            "entity": "Ministère de l'Éducation Nationale",
            "reference": "AO-2025/001/MEN",
            "description": "Fourniture de matériel de bureau destiné aux écoles primaires",
            "deadline": "2025-02-15",
        },
        "expected": True,  # Should be detected as duplicate
    },
    {
        "name": "Similaires mais différents (entités différentes)",
        "item1": {
            "id": "tender_2a",
            "title": "Construction de salles de classe",
            "entity": "Commune de Ouagadougou",
            "reference": "AO-2025/010/CO",
            "description": "Construction de 5 salles de classe à l'école primaire A",
            "deadline": "2025-03-01",
        },
        "item2": {
            "id": "tender_2b",
            "title": "Construction de salles de classe",
            "entity": "Commune de Bobo-Dioulasso",
            "reference": "AO-2025/015/CBD",
            "description": "Construction de 5 salles de classe à l'école primaire B",
            "deadline": "2025-03-01",
        },
        "expected": False,  # Should NOT be detected as duplicate
    },
    {
        "name": "Complètement différents",
        "item1": {
            "id": "tender_3a",
            "title": "Acquisition de véhicules administratifs",
            "entity": "Ministère de la Défense",
            "reference": "AO-2025/050/MD",
            "description": "Achat de 10 véhicules 4x4 pour les besoins administratifs",
            "deadline": "2025-04-20",
        },
        "item2": {
            "id": "tender_3b",
            "title": "Développement de logiciel de gestion",
            "entity": "Ministère de la Santé",
            "reference": "AO-2025/100/MS",
            "description": "Développement d'un système de gestion hospitalière",
            "deadline": "2025-05-15",
        },
        "expected": False,  # Should NOT be detected as duplicate
    },
]


def test_deduplication():
    """Test duplicate detection with LLM."""

    print("=" * 80)
    print("TEST: Détection de doublons avec LLM")
    print("=" * 80)

    results = []

    for idx, test_case in enumerate(test_pairs, 1):
        print(f"\n{'=' * 80}")
        print(f"Test {idx}: {test_case['name']}")
        print("=" * 80)

        item1 = test_case["item1"]
        item2 = test_case["item2"]

        print("\n📄 Item 1:")
        print(f"  Titre: {item1['title']}")
        print(f"  Entité: {item1['entity']}")
        print(f"  Référence: {item1['reference']}")

        print("\n📄 Item 2:")
        print(f"  Titre: {item2['title']}")
        print(f"  Entité: {item2['entity']}")
        print(f"  Référence: {item2['reference']}")

        print("\n🔄 Vérification de duplication en cours...")

        try:
            is_duplicate, confidence, reasoning = check_duplicate_with_llm(
                item1=item1, item2=item2
            )

            # Determine if result matches expectation
            expected = test_case["expected"]
            match = is_duplicate == expected
            status = "✅ CORRECT" if match else "❌ INCORRECT"

            print(f"\n{status}")
            print(f"  Résultat: {'DOUBLON' if is_duplicate else 'UNIQUE'}")
            print(f"  Attendu: {'DOUBLON' if expected else 'UNIQUE'}")
            print(f"  Confiance: {confidence:.2%}")
            print("\n  Raisonnement:")
            for line in reasoning.split("\n"):
                if line.strip():
                    print(f"    {line.strip()}")

            results.append(
                {
                    "test": test_case["name"],
                    "match": match,
                    "is_duplicate": is_duplicate,
                    "confidence": confidence,
                }
            )

        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            import traceback

            traceback.print_exc()
            results.append({"test": test_case["name"], "match": False, "error": str(e)})

    # Summary
    print("\n" + "=" * 80)
    print("RÉSUMÉ DES TESTS")
    print("=" * 80)

    total = len(results)
    correct = sum(1 for r in results if r.get("match", False))
    accuracy = (correct / total * 100) if total > 0 else 0

    print(f"\nTests réussis: {correct}/{total} ({accuracy:.1f}%)")

    for result in results:
        status = "✅" if result.get("match") else "❌"
        print(f"\n{status} {result['test']}")
        if "error" in result:
            print(f"   Erreur: {result['error']}")
        else:
            print(
                f"   Détecté: {'Doublon' if result.get('is_duplicate') else 'Unique'}"
            )
            print(f"   Confiance: {result.get('confidence', 0):.2%}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    print("\n🧪 Testing Deduplication Logic\n")
    test_deduplication()


# ---------------------------------------------------------------------------
# DB-first cfg() tests — use TenderAIState, not MockState
# ---------------------------------------------------------------------------

import os  # noqa: E402 — grouped with the env var setup it configures below, not with the file's top-of-file imports

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault(
    "TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
)
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import hashlib  # noqa: E402

import pytest  # noqa: E402

from tenderai.agents.graph import TenderAIState  # noqa: E402
from tenderai.agents.nodes.deduplicate import deduplicate_node  # noqa: E402

COUNTRY_CONFIG_DEDUP = {
    "pipeline": {
        "use_llm_classification": False,
        "min_relevance_score": 0.3,
        "deduplication_method": "hash_only",
        "deduplication_threshold": 0.85,
        "pdf_timeout": 30,
        "max_file_size_mb": 10,
    },
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
    "prompts": {
        "deduplication": {"system": "", "user_template": ""},
        "extraction": {"system": "", "user_template": ""},
        "classification": {"system": "", "user_template": ""},
        "summarization": {"system": "", "user_template": ""},
    },
}


def test_deduplicate_hash_only_uses_country_config():
    def h(s):
        return hashlib.sha256(s.encode()).hexdigest()

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_DEDUP,
        items_parsed=[
            {"id": "a", "title": "Tender A", "content_hash": h("unique_a")},
            {"id": "b", "title": "Tender B", "content_hash": h("unique_b")},
            {"id": "c", "title": "Tender A dup", "content_hash": h("unique_a")},
        ],
    )
    result = deduplicate_node(state)
    unique_ids = [i["id"] for i in result.unique_items]
    assert "a" in unique_ids
    assert "b" in unique_ids
    assert "c" not in unique_ids


def test_deduplicate_fails_hard_if_config_missing():
    state = TenderAIState(
        country_id=1,
        country_config={},
        items_parsed=[{"id": "a", "title": "T", "content_hash": "abc"}],
    )
    with pytest.raises(RuntimeError, match="Missing DB config"):
        deduplicate_node(state)


COUNTRY_CONFIG_HASH_SIMILARITY = {
    **COUNTRY_CONFIG_DEDUP,
    "pipeline": {
        **COUNTRY_CONFIG_DEDUP["pipeline"],
        "deduplication_method": "hash_similarity",
        "deduplication_threshold": 0.75,
    },
}


def test_hash_similarity_trusts_differing_reference_numbers():
    """constat #13: two items with different reference numbers must not be
    merged just because their title text is superficially similar (addenda,
    boilerplate templates) — real cases hit up to 99.1% text similarity."""
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_HASH_SIMILARITY,
        items_parsed=[
            {
                "id": "a",
                "title": "Addendum au marché de fourniture de data center",
                "reference": "DAOI-N022-2026",
                "content_hash": "hash-a",
            },
            {
                "id": "b",
                "title": "Addendum au marché de fourniture de data center",
                "reference": "DAOI-N071-2026",
                "content_hash": "hash-b",
            },
        ],
    )
    result = deduplicate_node(state)
    unique_ids = {i["id"] for i in result.unique_items}
    assert unique_ids == {"a", "b"}


def test_hash_similarity_still_merges_same_reference_number():
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_HASH_SIMILARITY,
        items_parsed=[
            {
                "id": "a",
                "title": "Fourniture de matériel informatique",
                "reference": "AO-2026-042",
                "content_hash": "hash-a",
            },
            {
                "id": "b",
                "title": "Fourniture matériel informatique (republication)",
                "reference": "AO-2026-042",
                "content_hash": "hash-b",
            },
        ],
    )
    result = deduplicate_node(state)
    unique_ids = {i["id"] for i in result.unique_items}
    assert unique_ids == {"a"}


def test_deduplicate_logs_discarded_items_with_reason(monkeypatch):
    """constat #23: discarded items must be logged with their reason, not
    just silently dropped — previously only survivors were logged."""
    logged = {}

    def _fake_log_node_output(node_name, data, run_id=None, append=False):
        logged[node_name] = data

    monkeypatch.setattr(
        "tenderai.agents.nodes.deduplicate.log_node_output", _fake_log_node_output
    )

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_HASH_SIMILARITY,
        items_parsed=[
            {
                "id": "a",
                "title": "Fourniture de matériel informatique",
                "reference": "AO-2026-042",
                "content_hash": "hash-a",
            },
            {
                "id": "b",
                "title": "Fourniture matériel informatique (republication)",
                "reference": "AO-2026-042",
                "content_hash": "hash-b",
            },
        ],
    )
    deduplicate_node(state)

    assert "deduplicate_discarded" in logged
    discarded = logged["deduplicate_discarded"]
    assert len(discarded) == 1
    assert discarded[0]["id"] == "b"
    assert discarded[0]["duplicate_reason"] == "same_reference_number"
    assert discarded[0]["duplicate_of_id"] == "a"
