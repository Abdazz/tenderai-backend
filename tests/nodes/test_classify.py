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
