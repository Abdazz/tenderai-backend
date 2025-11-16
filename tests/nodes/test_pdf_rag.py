"""Test PDF RAG extraction node independently with real PDF from DGCMEF."""

import sys
sys.path.insert(0, '/app/src')

import json
import tempfile
import requests
from pathlib import Path
from datetime import datetime

from tenderai_bf.agents.nodes.parse_pdf_rag import (
    extract_text_from_pdf,
    split_into_chunks,
    parse_pdf_with_rag
)

# Real PDF URL from DGCMEF
PDF_URL = "https://dgcmef.gov.bf/sites/default/files/2025-11/Quotidien%20N%C2%B04269.pdf"

# Output JSON file path (logs directory is mounted and confirmed writable)
OUTPUT_JSON = "/app/logs/test_extracted_tenders.json"


def clear_json_file():
    """Clear the output JSON file before starting extraction."""
    print(f"\n🗑️  Nettoyage du fichier JSON: {OUTPUT_JSON}")
    try:
        with open(OUTPUT_JSON, 'w') as f:
            json.dump([], f)
        print("✅ Fichier JSON vidé")
    except Exception as e:
        print(f"⚠️  Erreur lors du nettoyage: {e}")


def save_tenders_to_json(tenders: list, test_name: str):
    """Save extracted tenders to JSON file.
    
    Args:
        tenders: List of extracted tender dictionaries
        test_name: Name of the test that extracted the tenders
    """
    if not tenders:
        print("⚠️  Aucun tender à sauvegarder")
        return
    
    try:
        # Read existing data
        try:
            with open(OUTPUT_JSON, 'r') as f:
                existing_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing_data = []
        
        # Add metadata to each tender
        timestamp = datetime.now().isoformat()
        for tender in tenders:
            tender['_test_name'] = test_name
            tender['_extracted_at'] = timestamp
        
        # Append new tenders
        existing_data.extend(tenders)
        
        # Save back to file
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Tenders sauvegardés dans: {OUTPUT_JSON}")
        print(f"   Nombre ajouté: {len(tenders)}")
        print(f"   Total dans le fichier: {len(existing_data)}")
        
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde: {e}")


def download_pdf(url: str) -> str:
    """Download PDF from URL and save to temporary file.
    
    Args:
        url: URL of the PDF to download
        
    Returns:
        Path to the downloaded PDF file
    """
    print(f"\n🌐 Téléchargement du PDF depuis:")
    print(f"   {url}")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_file.write(response.content)
        temp_file.close()
        
        file_size_mb = len(response.content) / (1024 * 1024)
        print(f"✅ PDF téléchargé: {temp_file.name}")
        print(f"   Taille: {file_size_mb:.2f} MB")
        
        return temp_file.name
        
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement: {e}")
        raise


def test_extract_text():
    """Test text extraction from real DGCMEF PDF."""
    
    print("\n" + "=" * 80)
    print("TEST 1: Extraction de texte depuis PDF réel (DGCMEF)")
    print("=" * 80)
    
    # Download PDF
    pdf_path = download_pdf(PDF_URL)
    
    try:
        # Extract text
        print("\n🔄 Extraction du texte avec Docling...")
        text = extract_text_from_pdf(pdf_path)
        
        print("\n✅ Texte extrait avec succès!")
        print(f"   Longueur: {len(text)} caractères")
        print(f"   Mots: ~{len(text.split())} mots")
        print(f"   Lignes: ~{len(text.splitlines())} lignes")
        
        print("\n📄 Extrait (1000 premiers caractères):")
        print("-" * 80)
        print(text[:1000])
        print("-" * 80)
        
        # Check for tender-related keywords
        keywords = ['appel', 'offres', 'marché', 'consultation', 'avis']
        found_keywords = [kw for kw in keywords if kw.lower() in text.lower()]
        print(f"\n🔍 Mots-clés trouvés: {', '.join(found_keywords) if found_keywords else 'aucun'}")
        
        return text
        
    finally:
        # Cleanup
        Path(pdf_path).unlink(missing_ok=True)


def test_chunk_splitting():
    """Test text chunking with RecursiveCharacterTextSplitter on real PDF."""
    
    print("\n" + "=" * 80)
    print("TEST 2: Découpage en chunks (RAG) - PDF réel")
    print("=" * 80)
    
    # Download PDF
    pdf_path = download_pdf(PDF_URL)
    
    try:
        # Extract text
        text = extract_text_from_pdf(pdf_path)
        
        print(f"\n📄 Texte extrait: {len(text)} caractères")
        
        # Split into chunks
        print("\n🔄 Découpage en chunks...")
        chunks = split_into_chunks(text)
        
        print("\n✅ Découpage terminé!")
        print(f"   Nombre de chunks: {len(chunks)}")
        print(f"   Taille moyenne: {sum(len(c) for c in chunks) / len(chunks):.0f} caractères")
        print(f"   Chunk min: {min(len(c) for c in chunks)} caractères")
        print(f"   Chunk max: {max(len(c) for c in chunks)} caractères")
        
        print("\n📋 Aperçu des chunks:")
        for i, chunk in enumerate(chunks[:3], 1):  # Show first 3 chunks
            print(f"\n--- Chunk {i} ({len(chunk)} chars) ---")
            print(chunk[:300] + "..." if len(chunk) > 300 else chunk)
        
        if len(chunks) > 3:
            print(f"\n... et {len(chunks) - 3} autres chunks")
        
        return chunks
        
    finally:
        Path(pdf_path).unlink(missing_ok=True)


def test_full_rag_extraction():
    """Test complete RAG-based extraction pipeline on real DGCMEF PDF."""
    
    print("\n" + "=" * 80)
    print("TEST 3: Extraction complète avec RAG + LLM - PDF réel DGCMEF")
    print("=" * 80)
    
    # Download PDF
    pdf_path = download_pdf(PDF_URL)
    
    try:
        print(f"\n📄 PDF: {pdf_path}")
        print("\n🔄 Extraction RAG en cours...")
        print("   (Indexation vectorielle + recherche sémantique + LLM)")
        print("   ⚠️  Cela peut prendre plusieurs minutes...")
        
        # Run full RAG extraction
        tenders = parse_pdf_with_rag(
            pdf_path=pdf_path,
            source_name="DGCMEF_QUOTIDIEN_4269",
            filename="Quotidien N°4269.pdf",
            metadata={"source": "dgcmef", "type": "quotidien"},
            use_llm=True,
            use_direct_extraction=False  # Use RAG, not direct extraction
        )
        
        print("\n✅ Extraction terminée!")
        print(f"   Tenders extraits: {len(tenders)}")
        
        # Save to JSON file
        save_tenders_to_json(tenders, "RAG_extraction")
        
        if tenders:
            print("\n📋 Tenders extraits du Quotidien N°4269:")
            print("=" * 80)
            for i, tender in enumerate(tenders, 1):
                print(f"\n🎯 Tender {i}/{len(tenders)}:")
                print(f"   Entité: {tender.get('entity', 'N/A')}")
                print(f"   Référence: {tender.get('reference', 'N/A')}")
                print(f"   Catégorie: {tender.get('category', 'N/A')}")
                print(f"   Budget: {tender.get('budget', 'N/A')}")
                print(f"   Deadline: {tender.get('deadline', 'N/A')}")
                print(f"   Location: {tender.get('location', 'N/A')}")
                desc = tender.get('description', 'N/A')
                print(f"   Description: {desc[:200]}..." if len(desc) > 200 else f"   Description: {desc}")
                print(f"   Keywords: {', '.join(tender.get('keywords', []))}")
                print(f"   Relevance: {tender.get('relevance_score', 0):.2f}")
        else:
            print("\n⚠️ Aucun tender extrait")
            print("   Vérifiez les logs pour voir les détails de l'extraction")
        
        return tenders
        
    finally:
        Path(pdf_path).unlink(missing_ok=True)


def test_direct_extraction():
    """Test direct extraction (no RAG, full text to LLM) on real PDF."""
    
    print("\n" + "=" * 80)
    print("TEST 4: Extraction directe (sans RAG) - PDF réel")
    print("=" * 80)
    
    # Download PDF
    pdf_path = download_pdf(PDF_URL)
    
    try:
        print(f"\n📄 PDF: {pdf_path}")
        print("\n🔄 Extraction directe en cours...")
        print("   (Texte complet envoyé au LLM, pas de RAG)")
        print("   ⚠️  Peut échouer si le PDF est trop grand pour le contexte LLM")
        
        # Run direct extraction (bypass RAG)
        tenders = parse_pdf_with_rag(
            pdf_path=pdf_path,
            source_name="DGCMEF_QUOTIDIEN_4269_DIRECT",
            filename="Quotidien N°4269.pdf",
            metadata={"source": "dgcmef", "type": "quotidien"},
            use_llm=True,
            use_direct_extraction=True  # Skip RAG
        )
        
        print("\n✅ Extraction terminée!")
        print(f"   Tenders extraits: {len(tenders)}")
        
        # Save to JSON file
        save_tenders_to_json(tenders, "direct_extraction")
        
        if tenders:
            print("\n📋 Résultats:")
            for i, tender in enumerate(tenders[:5], 1):  # Show first 5
                print(f"\n   [{i}] {tender.get('reference', 'N/A')}")
                print(f"       Entité: {tender.get('entity', 'N/A')[:50]}...")
                print(f"       Budget: {tender.get('budget', 'N/A')}")
                print(f"       Deadline: {tender.get('deadline', 'N/A')}")
            if len(tenders) > 5:
                print(f"\n   ... et {len(tenders) - 5} autres tenders")
        else:
            print("\n⚠️ Aucun tender extrait")
        
        return tenders
        
    finally:
        Path(pdf_path).unlink(missing_ok=True)


if __name__ == "__main__":
    print("\n🧪 Testing PDF RAG Extraction Pipeline\n")
    
    # Clear JSON file before starting
    clear_json_file()
    
    # Run all tests
    # print("1️⃣ Test extraction de texte")
    # test_extract_text()
    
    # print("\n\n2️⃣ Test découpage en chunks")
    # test_chunk_splitting()
    
    # print("\n\n3️⃣ Test extraction RAG complète")
    # test_full_rag_extraction()
    
    print("\n\n4️⃣ Test extraction directe")
    test_direct_extraction()
    
    print("\n\n✅ Tous les tests terminés!")
    print(f"📄 Résultats sauvegardés dans: {OUTPUT_JSON}")
    print("=" * 80)
