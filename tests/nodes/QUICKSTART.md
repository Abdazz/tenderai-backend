# Quick Start - Node Testing

## Setup Complete ✅

The testing infrastructure is ready to use! All test files have been created.

## Run Tests Now

### Individual Tests

```bash
# Test summarization (generates French summaries)
docker compose exec api python /app/tests/nodes/test_summarize.py

# Test deduplication (detects duplicate tenders)
docker compose exec api python /app/tests/nodes/test_deduplicate.py

# Test PDF RAG extraction (real DGCMEF PDF)
docker compose exec api python /app/tests/nodes/test_pdf_rag.py

# Test all at once
docker compose exec api python /app/tests/nodes/run_all_tests.py
```

### Check Extracted Tenders

The PDF RAG test saves results to JSON:

```bash
# View extracted tenders
cat tests/nodes/extracted_tenders.json

# Or inside Docker
docker compose exec api cat /app/tests/nodes/extracted_tenders.json | jq .
```

### What's Working

✅ **test_summarize.py** - French summary generation (3-4 seconds)
✅ **test_deduplicate.py** - Duplicate detection with 100% test accuracy
⚠️ **test_extraction.py** - Has Groq API issues with structured output (known bug)
⚠️ **test_classify.py** - Needs minor fixes

## Quick Test Results

**Summarization Test** - ✅ WORKING
```
Résumé généré avec succès!
Longueur: 512 caractères
Mots: 69 mots
```

**Deduplication Test** - ✅ WORKING (100% accuracy)
```
Tests réussis: 3/3 (100.0%)

✅ Duplicates évidents (même référence) - Détecté: Doublon (80% confiance)
✅ Similaires mais différents - Détecté: Unique (20% confiance) 
✅ Complètement différents - Détecté: Unique (20% confiance)
```

## Current Configuration

- **Model**: llama-3.1-8b-instant (fast, 8B params)
- **Provider**: Groq
- **Prompts**: French (from settings.yaml)
- **Chunk Size**: 2400 characters

## Files Created

```
tests/nodes/
├── README.md              # Full documentation
├── QUICKSTART.md         # This file
├── run_all_tests.py      # Test runner
├── test_extraction.py    # ⚠️ Structured output issues
├── test_classify.py      # Keyword/LLM classification
├── test_summarize.py     # ✅ French summarization
└── test_deduplicate.py   # ✅ Duplicate detection
```

## Next Steps

1. **Test your changes**: Run specific node tests after code modifications
2. **Iterate faster**: No need to run full 10-minute pipeline
3. **Save API costs**: Test with sample data instead of real PDFs
4. **Fix extraction**: Switch to llama-3.3-70b-versatile or OpenAI for structured output

## Troubleshooting

### Groq Rate Limits
If you hit rate limits (429 error):
- Using llama-3.1-8b-instant helps (lower limits)
- Wait for quota reset
- Switch to OpenAI: `LLM_PROVIDER=openai` in .env

### Structured Output Fails
Groq's tool calling with llama-3.1-8b-instant is unreliable. Use:
- llama-3.3-70b-versatile (more stable)
- OpenAI models (very reliable)
- JSON parsing instead of structured output

## Examples

Run summarization test and see French summary:
```bash
docker compose exec api python /app/tests/nodes/test_summarize.py
```

Run deduplication with 3 test cases:
```bash
docker compose exec api python /app/tests/nodes/test_deduplicate.py
```

See all tests with colored output:
```bash
docker compose exec api python /app/tests/nodes/run_all_tests.py
```

## Performance

With llama-3.1-8b-instant:
- Summarization: ~3-4 seconds
- Deduplication: ~2-3 seconds per pair
- Total test suite: ~30 seconds

## Documentation

See `README.md` in this directory for:
- Detailed test descriptions
- Expected outputs
- Adding new tests
- Best practices
- Full troubleshooting guide
