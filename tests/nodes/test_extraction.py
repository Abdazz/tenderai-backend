"""Test extraction node independently."""

import sys

sys.path.insert(0, "/app/src")

from tenderai.agents.extraction import extract_tenders_structured

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


def test_parse_extract_tavily_search_item():
    """Tavily search item is normalized into a Notice-compatible dict."""
    from unittest.mock import MagicMock

    from tenderai.agents.nodes.parse_extract import parse_extract_node

    state = MagicMock()
    state.error_occurred = False
    state.run_id = "run-test"
    state.country_config = {"rag": {}, "llm": {}}
    state.items_raw = [
        {
            "url": "https://example.com/tenders/123",
            "content": "Fourniture équipements réseau pour le MEFP Sénégal...",
            "status": "success",
            "parser_type": "tavily_search",
            "source": "tavily",
            "title": "Appel d'offres réseau MEFP",
            "score": 0.91,
            "fetched_at": "2026-06-03T10:00:00",
        }
    ]
    state.items_parsed = []
    state.update_stats = MagicMock()

    result = parse_extract_node(state)

    assert len(result.items_parsed) == 1
    item = result.items_parsed[0]
    assert item["title"] == "Appel d'offres réseau MEFP"
    assert item["url"] == "https://example.com/tenders/123"
    assert "réseau" in item["description"]
    assert item["source"] == "tavily"


def test_parse_extract_tavily_extract_item():
    """Tavily extract item is normalized into a Notice-compatible dict."""
    from unittest.mock import MagicMock

    from tenderai.agents.nodes.parse_extract import parse_extract_node

    state = MagicMock()
    state.error_occurred = False
    state.run_id = "run-test"
    state.country_config = {"rag": {}, "llm": {}}
    state.items_raw = [
        {
            "url": "https://gov.example.com/tenders",
            "content": "Liste des marchés publics en cours...",
            "status": "success",
            "parser_type": "tavily_extract",
            "source": "tavily",
            "title": "Portail marchés Sénégal",
            "score": None,
            "fetched_at": "2026-06-03T10:00:00",
        }
    ]
    state.items_parsed = []
    state.update_stats = MagicMock()

    result = parse_extract_node(state)

    assert len(result.items_parsed) == 1
    item = result.items_parsed[0]
    assert item["source"] == "tavily"
    assert item["url"] == "https://gov.example.com/tenders"


def test_parse_quotidien_structured_no_relevance_fields():
    """Structural extraction only — no relevance judgment embedded."""
    from tenderai.agents.nodes.parse_pdf_structured import TenderBlock

    # TenderBlock itself must no longer accept is_relevant/domain/relevance_score
    block_fields = TenderBlock.model_fields.keys()
    assert "is_relevant" not in block_fields
    assert "domain" not in block_fields
    assert "relevance_score" not in block_fields
    assert "is_results_notice" in block_fields  # kept — structural signal


def test_parse_quotidien_structured_carries_source_name():
    import inspect

    from tenderai.agents.nodes.parse_pdf_structured import (
        parse_quotidien_structured,
    )

    params = inspect.signature(parse_quotidien_structured).parameters
    assert "source_name" in params


def test_parse_tavily_listing_no_relevance_fields():
    from tenderai.agents.nodes.parse_tavily_listing import TenderItem

    item_fields = TenderItem.model_fields.keys()
    assert "is_relevant" not in item_fields
    assert "domain" not in item_fields
    assert "relevance_score" not in item_fields
    assert "is_results_notice" in item_fields  # kept — structural signal


def test_ledevoir_ocr_prompt_has_no_relevance_field():
    from tenderai.agents.nodes.fetch_ledevoir import _OCR_PROMPT

    assert "is_relevant" not in _OCR_PROMPT
