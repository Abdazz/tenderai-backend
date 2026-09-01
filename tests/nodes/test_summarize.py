"""Test summarization node independently."""

import sys

sys.path.insert(0, "/app/src")

from tenderai.agents.nodes.summarize import generate_summary_with_llm

# Sample tender to summarize
sample_tender = {
    "id": "test_summary_1",
    "title": "Acquisition de fournitures médicales et équipements hospitaliers",
    "entity": "Centre Hospitalier Universitaire Yalgado Ouédraogo",
    "reference": "AO-2025/001/CHU-YO/DAF",
    "description": """
    Le Centre Hospitalier Universitaire Yalgado Ouédraogo lance un appel d'offres
    pour l'acquisition de fournitures médicales et équipements hospitaliers destinés
    aux services de chirurgie, maternité et pédiatrie.

    Lot 1: Équipements de bloc opératoire (tables chirurgicales, éclairages, instruments)
    Lot 2: Matériel de maternité (lits médicalisés, tables d'accouchement, monitoring fœtal)
    Lot 3: Équipements de pédiatrie (incubateurs, respirateurs néonataux, moniteurs)

    Budget estimatif: 450 000 000 FCFA
    Date limite de dépôt: 15 mars 2025
    Délai de livraison: 90 jours après notification
    """,
    "deadline": "2025-03-15",
    "budget": 450000000,
    "category": "Fournitures médicales",
    "location": "Ouagadougou, Burkina Faso",
    "contact": "daf@chu-yo.bf",
    "keywords": ["médical", "chirurgie", "maternité", "pédiatrie", "équipements"],
    "source_url": "https://example.com/ao-2025-001",
}


def test_summarization():
    """Test summary generation with LLM."""

    print("=" * 80)
    print("TEST: Génération de résumé avec LLM")
    print("=" * 80)

    print("\n📄 Appel d'offres à résumer:")
    print(f"  ID: {sample_tender['id']}")
    print(f"  Titre: {sample_tender['title']}")
    print(f"  Entité: {sample_tender['entity']}")
    print(f"  Budget: {sample_tender.get('budget', 'N/A'):,} FCFA")
    print(f"  Date limite: {sample_tender.get('deadline', 'N/A')}")

    print("\n🔄 Génération du résumé en cours...")

    try:
        summary = generate_summary_with_llm(item=sample_tender)

        print("\n✅ Résumé généré avec succès!")
        print("\n" + "-" * 80)
        print("RÉSUMÉ:")
        print("-" * 80)
        print(summary)
        print("-" * 80)

        # Basic validation
        print("\n📊 Validation du résumé:")
        print(f"  Longueur: {len(summary)} caractères")
        print(f"  Mots: {len(summary.split())} mots")

        # Check if key information is present
        key_elements = {
            "Entité": sample_tender["entity"][:20],
            "Référence": sample_tender["reference"],
            "Budget": "450",
            "Date": "2025",
        }

        print("\n  Éléments clés présents:")
        for element, value in key_elements.items():
            present = value.lower() in summary.lower()
            status = "✅" if present else "❌"
            print(f"    {status} {element}: {value}")

    except Exception as e:
        print(f"\n❌ Erreur lors de la génération: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)


if __name__ == "__main__":
    print("\n🧪 Testing Summary Generation\n")
    test_summarization()
