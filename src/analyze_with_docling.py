"""Analyze quotidien PDF structure."""

from pathlib import Path
import sys
sys.path.insert(0, '/app/src')

from tenderai_bf.utils.pdf import extract_pdf_text_from_bytes

def analyze_quotidien():
    """Analyze the quotidien PDF structure."""
    
    pdf_path = Path('/app/src/quotidien_sample.pdf')
    
    print("=" * 80)
    print("ANALYZING QUOTIDIEN PDF STRUCTURE")
    print("=" * 80)
    
    # Extract text from PDF
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    
    text = extract_pdf_text_from_bytes(pdf_bytes)
    markdown = text  # Use text directly
    
    print(f"\n📄 Document info:")
    print(f"  - Total characters: {len(text)}")
    print(f"  - Total lines: {len(text.splitlines())}")
    
    # Find AVIS sections
    import re
    
    # Look for section markers
    print("\n" + "=" * 80)
    print("SEARCHING FOR SECTION MARKERS")
    print("=" * 80)
    
    sections_found = {
        'RESULTATS': markdown.count('RESULTATS'),
        'RÉSULTATS': markdown.count('RÉSULTATS'),
        'AVIS': 0,
        'Fournitures et Services': markdown.count('Fournitures et Services'),
        'FOURNITURES ET SERVICES': markdown.count('FOURNITURES ET SERVICES'),
    }
    
    # Count AVIS patterns
    avis_patterns = [
        r"(?:^|\n)#+\s*AVIS",
        r"Avis d'Appel d'Offres",
        r"Avis de Demande de Prix",
    ]
    
    for pattern in avis_patterns:
        matches = re.findall(pattern, markdown, re.IGNORECASE | re.MULTILINE)
        print(f"Pattern '{pattern}': {len(matches)} matches")
        sections_found['AVIS'] += len(matches)
    
    print(f"\n📊 Section counts:")
    for section, count in sections_found.items():
        print(f"  - {section}: {count}")
    
    # Find where AVIS section starts
    print("\n" + "=" * 80)
    print("LOCATING AVIS SECTION")
    print("=" * 80)
    
    # Try different markers for the AVIS section
    markers = [
        'Fournitures et Services courants',
        'FOURNITURES ET SERVICES COURANTS',
        '## AVIS',
        '# AVIS',
    ]
    
    avis_start = -1
    marker_used = None
    
    for marker in markers:
        pos = markdown.find(marker)
        if pos != -1:
            avis_start = pos
            marker_used = marker
            print(f"✓ Found section marker: '{marker}' at position {pos}")
            break
    
    if avis_start == -1:
        print("❌ Could not find AVIS section marker")
        print("\nShowing first 2000 characters of markdown:")
        print("-" * 80)
        print(markdown[:2000])
        print("-" * 80)
        print("\nShowing last 2000 characters of markdown:")
        print("-" * 80)
        print(markdown[-2000:])
    else:
        # Extract AVIS section
        avis_section = markdown[avis_start:]
        
        # Find where next major section starts (if any)
        next_section_patterns = [
            r'\n#{1,2}\s+(?!Avis)[A-Z]',  # Next heading that's not AVIS
        ]
        
        print(f"\n📄 AVIS section preview (first 3000 chars):")
        print("-" * 80)
        print(avis_section[:3000])
        print("-" * 80)
        
        # Try to identify individual tenders in AVIS section
        print("\n" + "=" * 80)
        print("IDENTIFYING INDIVIDUAL TENDERS")
        print("=" * 80)
        
        # Split by headers or entity names
        # Docling usually marks sections with ## or ###
        tender_headers = re.findall(r'^#{2,4}\s+(.+)$', avis_section, re.MULTILINE)
        
        print(f"\nFound {len(tender_headers)} headers in AVIS section:")
        for i, header in enumerate(tender_headers[:20], 1):  # Show first 20
            print(f"  {i}. {header}")
        
        # Also look for entity names (ALL CAPS paragraphs)
        entity_pattern = r'\n([A-ZÀÂÄÇÉÈÊËÏÎÔÙÛÜ\s\-\']{30,150})\n'
        entities = re.findall(entity_pattern, avis_section)
        
        print(f"\n\nFound {len(entities)} potential entity names (ALL CAPS):")
        for i, entity in enumerate(entities[:20], 1):
            print(f"  {i}. {entity.strip()}")

if __name__ == '__main__':
    analyze_quotidien()
