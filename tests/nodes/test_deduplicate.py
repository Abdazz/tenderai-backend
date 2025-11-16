"""Test deduplication node independently."""

import sys
sys.path.insert(0, '/app/src')

from tenderai_bf.agents.nodes.deduplicate import check_duplicate_with_llm

# Sample tender pairs to test deduplication
test_pairs = [
    {
        'name': 'Duplicates évidents (même référence)',
        'item1': {
            'id': 'tender_1a',
            'title': 'Acquisition de fournitures de bureau',
            'entity': 'Ministère de l\'Éducation',
            'reference': 'AO-2025/001/MEN',
            'description': 'Fourniture de matériel de bureau pour les écoles primaires',
            'deadline': '2025-02-15'
        },
        'item2': {
            'id': 'tender_1b',
            'title': 'Acquisition de fournitures de bureau',
            'entity': 'Ministère de l\'Éducation Nationale',
            'reference': 'AO-2025/001/MEN',
            'description': 'Fourniture de matériel de bureau destiné aux écoles primaires',
            'deadline': '2025-02-15'
        },
        'expected': True  # Should be detected as duplicate
    },
    {
        'name': 'Similaires mais différents (entités différentes)',
        'item1': {
            'id': 'tender_2a',
            'title': 'Construction de salles de classe',
            'entity': 'Commune de Ouagadougou',
            'reference': 'AO-2025/010/CO',
            'description': 'Construction de 5 salles de classe à l\'école primaire A',
            'deadline': '2025-03-01'
        },
        'item2': {
            'id': 'tender_2b',
            'title': 'Construction de salles de classe',
            'entity': 'Commune de Bobo-Dioulasso',
            'reference': 'AO-2025/015/CBD',
            'description': 'Construction de 5 salles de classe à l\'école primaire B',
            'deadline': '2025-03-01'
        },
        'expected': False  # Should NOT be detected as duplicate
    },
    {
        'name': 'Complètement différents',
        'item1': {
            'id': 'tender_3a',
            'title': 'Acquisition de véhicules administratifs',
            'entity': 'Ministère de la Défense',
            'reference': 'AO-2025/050/MD',
            'description': 'Achat de 10 véhicules 4x4 pour les besoins administratifs',
            'deadline': '2025-04-20'
        },
        'item2': {
            'id': 'tender_3b',
            'title': 'Développement de logiciel de gestion',
            'entity': 'Ministère de la Santé',
            'reference': 'AO-2025/100/MS',
            'description': 'Développement d\'un système de gestion hospitalière',
            'deadline': '2025-05-15'
        },
        'expected': False  # Should NOT be detected as duplicate
    }
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
        print('=' * 80)
        
        item1 = test_case['item1']
        item2 = test_case['item2']
        
        print(f"\n📄 Item 1:")
        print(f"  Titre: {item1['title']}")
        print(f"  Entité: {item1['entity']}")
        print(f"  Référence: {item1['reference']}")
        
        print(f"\n📄 Item 2:")
        print(f"  Titre: {item2['title']}")
        print(f"  Entité: {item2['entity']}")
        print(f"  Référence: {item2['reference']}")
        
        print("\n🔄 Vérification de duplication en cours...")
        
        try:
            is_duplicate, confidence, reasoning = check_duplicate_with_llm(
                item1=item1,
                item2=item2
            )
            
            # Determine if result matches expectation
            expected = test_case['expected']
            match = (is_duplicate == expected)
            status = "✅ CORRECT" if match else "❌ INCORRECT"
            
            print(f"\n{status}")
            print(f"  Résultat: {'DOUBLON' if is_duplicate else 'UNIQUE'}")
            print(f"  Attendu: {'DOUBLON' if expected else 'UNIQUE'}")
            print(f"  Confiance: {confidence:.2%}")
            print(f"\n  Raisonnement:")
            for line in reasoning.split('\n'):
                if line.strip():
                    print(f"    {line.strip()}")
            
            results.append({
                'test': test_case['name'],
                'match': match,
                'is_duplicate': is_duplicate,
                'confidence': confidence
            })
            
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'test': test_case['name'],
                'match': False,
                'error': str(e)
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("RÉSUMÉ DES TESTS")
    print("=" * 80)
    
    total = len(results)
    correct = sum(1 for r in results if r.get('match', False))
    accuracy = (correct / total * 100) if total > 0 else 0
    
    print(f"\nTests réussis: {correct}/{total} ({accuracy:.1f}%)")
    
    for result in results:
        status = "✅" if result.get('match') else "❌"
        print(f"\n{status} {result['test']}")
        if 'error' in result:
            print(f"   Erreur: {result['error']}")
        else:
            print(f"   Détecté: {'Doublon' if result.get('is_duplicate') else 'Unique'}")
            print(f"   Confiance: {result.get('confidence', 0):.2%}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    print("\n🧪 Testing Deduplication Logic\n")
    test_deduplication()
