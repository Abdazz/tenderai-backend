#!/usr/bin/env python3
"""Test script to verify Ollama integration with langchain-ollama."""

import sys
from langchain_ollama import ChatOllama
from tenderai_bf.config import settings


def test_ollama_connection():
    """Test basic Ollama connectivity."""
    print("=" * 60)
    print("Testing Ollama Integration")
    print("=" * 60)
    
    print(f"\nConfiguration:")
    print(f"  • Ollama Base URL: {settings.llm.ollama_base_url}")
    print(f"  • Ollama Model: {settings.llm.ollama_model}")
    print(f"  • Temperature: {settings.llm.temperature}")
    print(f"  • Max Tokens: {settings.llm.max_tokens}")
    
    print("\n" + "-" * 60)
    print("Test 1: Basic Connection & Simple Query")
    print("-" * 60)
    
    try:
        llm = ChatOllama(
            base_url=settings.llm.ollama_base_url,
            model=settings.llm.ollama_model,
            temperature=settings.llm.temperature
        )
        
        response = llm.invoke("Say hello in one short sentence.")
        print(f"✓ Success!")
        print(f"  Response: {response.content}")
        
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    
    print("\n" + "-" * 60)
    print("Test 2: Structured Classification Query")
    print("-" * 60)
    
    try:
        classification_prompt = """Is this tender relevant for IT/Engineering services?

Tender: "Appel d'offres pour la fourniture de matériel informatique et réseau"

Answer with just 'YES' or 'NO' and a brief reason."""
        
        response = llm.invoke(classification_prompt)
        print(f"✓ Success!")
        print(f"  Response: {response.content}")
        
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    
    print("\n" + "-" * 60)
    print("Test 3: Summarization Query (French)")
    print("-" * 60)
    
    try:
        summary_prompt = """Résumez cet appel d'offres en 2-3 phrases:

Titre: APPEL D'OFFRES POUR L'ENTRETIEN ET LE NETTOYAGE D'INFRASTRUCTURES
Entité: MAIRIE DE OUAGADOUGOU
Catégorie: Services
Description: La mairie recherche un prestataire pour l'entretien des infrastructures publiques.

Résumé:"""
        
        response = llm.invoke(summary_prompt)
        print(f"✓ Success!")
        print(f"  Response: {response.content}")
        
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("✓ All tests passed! Ollama is working correctly.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_ollama_connection()
    sys.exit(0 if success else 1)
