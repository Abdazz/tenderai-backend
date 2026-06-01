"""Test extraction node independently."""

import sys

sys.path.insert(0, "/app/src")

from tenderai_bf.agents.extraction import extract_tenders_structured

# Sample French tender text
sample_text = """
AVIS D'APPEL D'OFFRES OUVERT N° 2025/001/MEFP/SG/DMP

Le Ministère de l'Économie et des Finances lance un appel d'offres ouvert pour :

Objet : Acquisition d'équipements informatiques et logiciels pour la modernisation du système d'information

Référence : AO-2025-001-IT
Entité : Direction des Marchés Publics
Budget estimatif : 150 000 000 FCFA
Localisation : Ouagadougou, Burkina Faso

Date limite de dépôt des offres : 30 novembre 2025 à 10h00

Les soumissionnaires doivent fournir :
- Matériel informatique (serveurs, postes de travail, imprimantes)
- Logiciels de gestion (ERP, base de données)
- Services d'installation et de formation

Contact : dmp@finances.gov.bf
"""


def test_extraction():
    """Test tender extraction from sample text."""

    print("=" * 80)
    print("TEST: Extraction de tenders")
    print("=" * 80)

    print("\nTexte source (extrait) :")
    print("-" * 80)
    print(sample_text[:200] + "...")
    print("-" * 80)

    print("\n🔄 Appel à extract_tenders_structured()...")

    result = extract_tenders_structured(
        context=sample_text, source_name="TEST_SOURCE", max_retries=2
    )

    print("\n✅ Extraction terminée")
    print(f"   Total extraits: {result.total_extracted}")
    print(f"   Confiance: {result.confidence}")
    print(f"   Nombre de tenders: {len(result.tenders)}")

    if result.tenders:
        print("\n📋 Tenders extraits :")
        print("-" * 80)
        for i, tender in enumerate(result.tenders, 1):
            print(f"\nTender {i}:")
            print(f"  Entité: {tender.entity}")
            print(f"  Référence: {tender.reference}")
            print(f"  Description: {tender.description[:100]}...")
            print(f"  Catégorie: {tender.category}")
            print(f"  Deadline: {tender.deadline}")
            print(f"  Budget: {tender.budget}")
            print(f"  Location: {tender.location}")
            print(f"  Keywords: {', '.join(tender.keywords)}")
            print(f"  Relevance Score: {tender.relevance_score}")
    else:
        print("\n⚠️ Aucun tender extrait")

    print("\n" + "=" * 80)
    return result


if __name__ == "__main__":
    test_extraction()
