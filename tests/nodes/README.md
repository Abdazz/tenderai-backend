# Node Testing Guide

## Overview

This directory contains independent test scripts for each pipeline node. These tests allow you to validate individual components without running the full workflow, which is especially useful for:

- **Faster development**: Test changes in seconds instead of running 10+ minute pipeline
- **Cost efficiency**: Avoid rate limits by testing specific nodes
- **Debugging**: Isolate issues to specific components
- **Development**: Iterate quickly on prompts and logic

## Available Tests

### 1. `test_extraction.py` - Tender Extraction
Tests structured extraction of tender information from French text using LLM.

**What it tests:**
- Parsing French tender announcements
- Structured data extraction (title, entity, reference, deadline, budget)
- Pydantic validation
- LLM model logging

**Sample data:** French AVIS D'APPEL D'OFFRES

### 2. `test_classify.py` - Classification
Tests both keyword-based and LLM-based classification methods.

**What it tests:**
- Keyword-based relevance scoring
- LLM-based classification with confidence scores
- Handling mixed categories (IT, BTP, Services)

**Sample data:** 3 tenders (IT hardware, construction, mobile app)

### 3. `test_summarize.py` - Summarization
Tests French summary generation for tenders.

**What it tests:**
- Summary generation with LLM
- Key information extraction
- Summary validation (length, presence of key elements)

**Sample data:** Medical equipment tender with detailed description

### 4. `test_deduplicate.py` - Deduplication
Tests duplicate detection using LLM reasoning.

**What it tests:**
- Obvious duplicates (same reference)
- Similar but different (different entities)
- Completely different tenders
- Confidence scoring and reasoning

**Sample data:** 3 tender pairs with known duplication status

### 5. `test_pdf_rag.py` - PDF RAG Extraction
Tests complete PDF extraction pipeline using real DGCMEF PDF files.

**What it tests:**
- PDF download from URL
- Text extraction with Docling (OCR disabled)
- Text chunking with RecursiveCharacterTextSplitter
- RAG-based extraction with vector search
- Direct extraction (full text to LLM)
- JSON output of extracted tenders

**Features:**
- Downloads real PDF from DGCMEF website
- Clears JSON output file before each run
- Saves all extracted tenders to `extracted_tenders.json`
- Adds metadata (_test_name, _extracted_at) to each tender

**Sample data:** Real Quotidien N°4269 PDF from https://dgcmef.gov.bf/

## Running Tests

### Run Individual Tests (in Docker)

```bash
# Test extraction
docker compose exec api python /app/tests/nodes/test_extraction.py

# Test classification
docker compose exec api python /app/tests/nodes/test_classify.py

# Test summarization
docker compose exec api python /app/tests/nodes/test_summarize.py

# Test deduplication
docker compose exec api python /app/tests/nodes/test_deduplicate.py

# Test PDF RAG extraction (real PDF from DGCMEF)
docker compose exec api python /app/tests/nodes/test_pdf_rag.py
```

### View Extracted Tenders

After running `test_pdf_rag.py`, check the extracted tenders:

```bash
# View JSON file with extracted tenders
docker compose exec api cat /app/tests/nodes/extracted_tenders.json | jq .

# Count extracted tenders
docker compose exec api cat /app/tests/nodes/extracted_tenders.json | jq 'length'

# View first tender
docker compose exec api cat /app/tests/nodes/extracted_tenders.json | jq '.[0]'
```

### Run All Tests

```bash
docker compose exec api python /app/tests/nodes/run_all_tests.py
```

This will:
- Run all 4 tests in sequence
- Show colored output (green=pass, red=fail)
- Display summary with pass/fail counts
- Exit with code 1 if any test fails

### Run Tests Locally (outside Docker)

If you have Python environment configured:

```bash
cd /home/yulcom/web/rfp-watch-ai

# Individual test
python tests/nodes/test_extraction.py

# All tests
python tests/nodes/run_all_tests.py
```

## Understanding Test Output

### Extraction Test Output
```
==================================================================================
TEST: Extraction structurée de tenders
==================================================================================

📋 Source: TEST_SOURCE
📄 Texte à extraire (500 premiers caractères):
  AVIS D'APPEL D'OFFRES OUVERT N° 2025/001/MEFP/SG/DMP...

🔄 Extraction en cours...

✅ Extraction réussie!
   Tenders extraits: 1
   Confiance moyenne: 0.85

📋 Tender 1:
   Titre: Fourniture de matériel informatique
   Entité: Ministère de l'Économie
   Référence: AO-2025/001/MEFP/SG/DMP
   Budget: 50,000,000 FCFA
   Date limite: 2025-02-28
   Confiance: 0.85
```

### Classification Test Output
```
==================================================================================
TEST: Classification par LLM
==================================================================================

📋 Items à classifier: 3
  - test_1: Acquisition de serveurs et équipements réseau...
  - test_2: Construction de routes rurales...
  - test_3: Développement application mobile de santé...

🔄 Classification LLM en cours...

✅ Classification terminée
   Items pertinents: 2

📌 Items pertinents :
  - test_1: Acquisition de serveurs et équipements réseau
    Score: 0.92
  - test_3: Développement application mobile de santé
    Score: 0.88
```

### Deduplication Test Output
```
==================================================================================
Test 1: Duplicates évidents (même référence)
==================================================================================

📄 Item 1:
  Titre: Acquisition de fournitures de bureau
  Entité: Ministère de l'Éducation
  Référence: AO-2025/001/MEN

📄 Item 2:
  Titre: Acquisition de fournitures de bureau
  Entité: Ministère de l'Éducation Nationale
  Référence: AO-2025/001/MEN

✅ CORRECT
  Résultat: DOUBLON
  Attendu: DOUBLON
  Confiance: 95.00%

  Raisonnement:
    Les deux items ont la même référence AO-2025/001/MEN
    Les entités sont essentiellement identiques
    Il s'agit clairement du même appel d'offres
```

## Test Configuration

Tests use the same configuration as the main application:

- **LLM Model**: Configured in `.env` (GROQ_MODEL, OPENAI_MODEL)
- **Prompts**: Loaded from `settings.yaml`
- **RAG Settings**: chunk_size, chunk_overlap from `settings.yaml`

To test with different models, modify `.env`:
```bash
# Fast/cheap model (good for testing)
GROQ_MODEL=llama-3.1-8b-instant

# More capable but slower
GROQ_MODEL=llama-3.3-70b-versatile
```

Then restart Docker:
```bash
docker compose down && docker compose up -d
```

## Adding New Tests

To create a test for a new node:

1. **Create test file**: `tests/nodes/test_yournode.py`

2. **Import the node function**:
```python
import sys
sys.path.insert(0, '/app/src')

from tenderai_bf.agents.nodes.yournode import your_function
```

3. **Create sample data**:
```python
sample_data = {
    'id': 'test_1',
    # ... your test data
}
```

4. **Write test function**:
```python
def test_yournode():
    print("=" * 80)
    print("TEST: Your Node Description")
    print("=" * 80)
    
    # Call your function
    result = your_function(sample_data)
    
    # Validate and display results
    print(f"Result: {result}")
    
if __name__ == "__main__":
    test_yournode()
```

5. **Add to `run_all_tests.py`**:
```python
TESTS = [
    # ... existing tests
    {
        'file': 'test_yournode.py',
        'name': 'Your Node',
        'description': 'Tests your node functionality'
    }
]
```

## Troubleshooting

### Test hangs or times out
- Default timeout: 60 seconds
- Check if LLM API is responding
- Verify network connectivity in Docker

### Import errors
```python
ModuleNotFoundError: No module named 'tenderai_bf'
```
**Solution:** Make sure `sys.path.insert(0, '/app/src')` is at the top of your test file

### LLM rate limit errors
```
Error code: 429 - Rate limit reached
```
**Solution:** 
- Use llama-3.1-8b-instant (faster, lower rate limits)
- Wait for quota to reset
- Reduce sample data size

### Groq structured output errors
```
Error code: 400 - tool_use_failed
```
**Known Issue:** Groq's structured output with llama-3.1-8b-instant can be unreliable.
**Workarounds:**
- Use llama-3.3-70b-versatile (more stable structured output)
- Switch to OpenAI (set LLM_PROVIDER=openai in .env)
- Modify extraction logic to use JSON parsing instead of Groq's tool calling

### Model not found
```
The model `llama-3.3-70b-versatile` does not exist
```
**Solution:** Check available models in Groq/OpenAI dashboard, update `.env`

## Best Practices

1. **Run tests before committing**: Validate changes don't break existing functionality
2. **Use small sample data**: Keep tests fast and within rate limits
3. **Test edge cases**: Empty inputs, malformed data, missing fields
4. **Mock when possible**: Consider mocking LLM calls for unit tests (not done here)
5. **Document expectations**: Add comments about what should happen

## Next Steps

- **Add pytest integration**: Convert to proper test framework
- **Add fixtures**: Create reusable test data in `tests/fixtures/`
- **Add mocks**: Create mock LLM responses to avoid API costs
- **CI/CD**: Automate testing in deployment pipeline
- **Coverage**: Add coverage reporting to identify untested code

## Performance Notes

With **llama-3.1-8b-instant**:
- Extraction: ~3-5 seconds
- Classification: ~2-3 seconds per item
- Summarization: ~3-4 seconds
- Deduplication: ~2-3 seconds per pair

With **llama-3.3-70b-versatile**:
- 2-3x slower but higher quality results
- More likely to hit rate limits
