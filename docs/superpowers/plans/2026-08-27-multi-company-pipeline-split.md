# Multi-Company Pipeline Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single-pipeline `agents/graph.py` into a harvest graph (fetch → parse → dedupe → persist) and a new delivery graph (classify → summarize → report → email), introduce `Notice` persistence (which the current pipeline never does at all), and neutralize harvest-side pre-classification (`classification_embedded`) so per-company classification is correct for any company, not just YULCOM's IT scope.

**Architecture:** `agents/graph.py` keeps `TenderAIState`/`_route_after_step`/`error_handler`/`_AppWrapper`/`cfg` (unchanged import paths — no file rename, to avoid touching 10+ files that import/patch `tenderai_bf.agents.graph` by string path) but `TenderAIGraph` becomes harvest-only, ending at a new `persist_notices` step. A new `agents/delivery_graph.py` holds `DeliveryGraph`, reusing `classify`/`summarize`/`compose_report`/`email_report` (adapted) plus two new nodes (`select_new_notices`, `mark_delivered`). `TenderAIState` gains `company_id`/`company_config`; a new `company_cfg()` in `agents/_cfg.py` mirrors `cfg()` for company-scoped settings.

**Tech Stack:** LangGraph (unchanged), SQLAlchemy (classic `Column()` style, matching every existing model), pytest with in-memory SQLite fixtures for DB-touching tests, `TenderAIState`/mock-state patterns matching existing node tests.

**Spec:** `docs/superpowers/specs/2026-08-26-multi-company-pipeline-split-design.md` (all 4 sections, plus its Scope Decisions and Open Risks)

## Global Constraints

- **No file rename.** `agents/graph.py` stays `agents/graph.py`; `TenderAIGraph`/`create_pipeline_graph`/`get_pipeline` keep their names (their *behavior* becomes harvest-only). This is a deliberate deviation from a literal reading of the spec's "splitting today's single agents/graph.py pipeline into two" — confirmed via `git grep` that 10 files (`cli.py`, `scheduler/schedule.py`, 8 test files) import from `tenderai_bf.agents.graph` by path, several via string-based `patch("tenderai_bf.agents.graph....")` targets that a rename would silently break. Renaming buys nothing functionally and adds real risk; not renaming is the ruling for this plan.
- **`Notice.id` and `CompanyNoticeStatus.id` are caller-supplied UUID strings** (`str(uuid.uuid4())`), not autoincrement — every insert in this plan supplies one explicitly.
- **Source attribution is best-effort**, not fixed by this plan. Verified directly against `main` (not assumed): almost no item type reliably carries a `source_id`/`source_name` that matches a `Source.id` row by the time it reaches `deduplicate` — only `pdf_rag` and `parse_tavily_listing.py`'s output carry a `source_name`-shaped field, and even that field is sometimes page-title-derived rather than the real `Source.name`. `persist_notices` (Task 8) uses an explicit 4-tier fallback (exact `source_name` match → substring `source` match → single-source-per-country default → skip-with-warning) rather than attempting full source-attribution correctness across 8+ upstream fetcher files — that is real, separate scope, out of bounds for this plan.
- **`min_relevance_score` moves from `CountrySettings["pipeline"]` to `CompanySettings["classification"]`** — this is an explicit instruction from the original `2026-08-23-multi-company-design.md` spec (Section 1, `CompanySettings` note), not something this plan invented. Every `cfg(state, "pipeline", "min_relevance_score")` call in `classify.py` becomes `company_cfg(state, "classification", "min_relevance_score")` — section AND key both change.
- **`cfg(state, "llm", "provider")` stays `cfg()` everywhere** (LLM provider/keys are explicitly global, never company-scoped, per the original spec). `cfg(state, "pipeline", "deduplication_method"/"deduplication_threshold")` also stays `cfg()` — deduplication runs in the harvest graph, which has no company context at all.
- **`email_report_node`'s `cfg(state, "email", "to_address")` stays `cfg()` unchanged** — this is a country-level "always include" address, orthogonal to per-company `Recipient` scoping; the original spec's `CompanySettings["email"]` section only covers `subject_prefix`/`signature` overrides, not `to_address`. Only the `Recipient` DB query gains a `company_id` filter.
- **Report/email branding is explicitly NOT expanded in this plan.** `report/docx_report.py`, `email/smtp_client.py`, `storage/minio_client.py` are untouched — `country_name` keeps flowing through them exactly as today. `Company.logo_url`/`subject_prefix`/`signature` are not read anywhere by this plan. This resolves the original spec's Open Risk #3 in favor of the minimal-diff option: recipients get correctly-scoped reports (by `company_id` + `country_id`), just without company-specific visual branding yet — a natural fit for the later Auth/API plan, which is where an admin would actually configure `Company.subject_prefix` through a UI.
- **`TenderBlock`/`TenderItem`'s `category`/`domain` field is dropped entirely, not redesigned.** Both currently populate `category` with an IT-relevance-biased value (`it_services`/`hors_perimetre`/etc.) rather than a neutral market category (`Notice.category`'s own comment says `# Biens, Services, Travaux`). Redesigning the prompt for genuine neutral categorization is a data-quality improvement outside this plan's actual goal (classification correctness); dropping the field (leaving `Notice.category` `NULL` for LLM-extracted items, matching what the `ungm`/`tavily_search` branches already do with `"category": "Autre"`) is the minimal, spec-consistent choice.
- **`run-once` requires both `--country`/`--company` together** (by code/slug) — no standalone harvest-only invocation via this command after this plan (per the design spec's Scope Decision 4).
- Every task's test command set is run with:
  ```
  TENDERAI_JWT_SECRET="test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx"
  TENDERAI_ADMIN_PASSWORD="test-admin-password-not-real"
  ```

---

## Task 1: `company_cfg()` accessor

**Files:**
- Modify: `src/tenderai_bf/agents/_cfg.py`
- Test: `tests/test_cfg_helper.py`

**Interfaces:**
- Produces: `company_cfg(state: Any, section: str, key: str) -> Any` — reads `state.company_config[section][key]`, raises `RuntimeError` (chained via `from e`) on missing key/attribute, mirroring `cfg()` exactly.

- [ ] **Step 1: Write the failing test**

Read `tests/test_cfg_helper.py` first to match its existing style, then append:

```python
def test_company_cfg_reads_company_config():
    from tenderai_bf.agents._cfg import company_cfg

    class FakeState:
        company_id = 5
        company_config = {"classification": {"min_relevance_score": 0.4}}

    assert company_cfg(FakeState(), "classification", "min_relevance_score") == 0.4


def test_company_cfg_fails_hard_if_missing():
    import pytest
    from tenderai_bf.agents._cfg import company_cfg

    class FakeState:
        company_id = 5
        company_config = {}

    with pytest.raises(RuntimeError, match="Missing DB config: company_id=5"):
        company_cfg(FakeState(), "classification", "min_relevance_score")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_cfg_helper.py -v --no-cov -k company_cfg`
Expected: FAIL — `ImportError: cannot import name 'company_cfg'`

- [ ] **Step 3: Add `company_cfg()`**

Current `src/tenderai_bf/agents/_cfg.py` in full:
```python
"""Fail-hard accessor for DB-seeded pipeline configuration.

Nodes import ``cfg`` from here instead of from ``graph`` to avoid circular
imports (graph.py imports node modules; node modules must not import graph.py).
"""

from typing import Any


def cfg(state: Any, section: str, key: str) -> Any:
    """Read state.country_config[section][key]. Raises RuntimeError if absent.

    Use this in every pipeline node instead of settings.* for operational config.
    Fail-hard: a missing key means the DB was not seeded — surface it immediately.
    """
    try:
        return state.country_config[section][key]
    except (KeyError, AttributeError) as e:
        country_id = getattr(state, "country_id", "?")
        raise RuntimeError(
            f"Missing DB config: country_id={country_id} "
            f"section='{section}' key='{key}' — run seed first"
        ) from e
```

Append, after `cfg()`:
```python


def company_cfg(state: Any, section: str, key: str) -> Any:
    """Read state.company_config[section][key]. Raises RuntimeError if absent.

    Use this in delivery-graph nodes instead of cfg() for company-scoped
    operational config (classification, scheduler, email overrides).
    Fail-hard: a missing key means the DB was not seeded — surface it immediately.
    """
    try:
        return state.company_config[section][key]
    except (KeyError, AttributeError) as e:
        company_id = getattr(state, "company_id", "?")
        raise RuntimeError(
            f"Missing DB config: company_id={company_id} "
            f"section='{section}' key='{key}' — run seed first"
        ) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_cfg_helper.py -v --no-cov`
Expected: PASS (all tests in the file, including pre-existing `cfg()` tests — confirms no regression)

- [ ] **Step 5: Commit**

```bash
git add src/tenderai_bf/agents/_cfg.py tests/test_cfg_helper.py
git commit -m "feat(agents): add company_cfg() accessor, mirrors cfg() for company-scoped config"
```

---

## Task 2: `TenderAIState` gains `company_id`/`company_config`

**Files:**
- Modify: `src/tenderai_bf/agents/graph.py:33-79` (the `TenderAIState` class)
- Test: `tests/test_pipeline_country.py` (or a new focused test — see Step 1)

**Interfaces:**
- Consumes: nothing new.
- Produces: `TenderAIState.company_id: int = 0`, `TenderAIState.company_config: dict[str, Any]` — read by `company_cfg()` (Task 1) and every delivery-graph node from Task 10 onward.

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_company_fields.py`:
```python
import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.agents.graph import TenderAIState


def test_state_defaults_company_fields():
    state = TenderAIState()
    assert state.company_id == 0
    assert state.company_config == {}


def test_state_accepts_company_fields():
    state = TenderAIState(company_id=3, company_config={"classification": {}})
    assert state.company_id == 3
    assert state.company_config == {"classification": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_state_company_fields.py -v --no-cov`
Expected: FAIL — `pydantic.error_wrappers.ValidationError` or `AttributeError` on `company_id`

- [ ] **Step 3: Add the fields**

Current relevant section of `src/tenderai_bf/agents/graph.py`:
```python
    # Country context — populated by run() before graph execution
    country_id: int = 0
    country_name: str = ""
    country_locale: str = "fr"
    country_config: dict[str, Any] = Field(default_factory=dict)
```

Change to:
```python
    # Country context — populated by run() before graph execution
    country_id: int = 0
    country_name: str = ""
    country_locale: str = "fr"
    country_config: dict[str, Any] = Field(default_factory=dict)

    # Company context — populated by DeliveryGraph.run() before graph execution;
    # unused (defaults) for harvest-graph runs.
    company_id: int = 0
    company_config: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_state_company_fields.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: same pass/fail counts as the pre-task baseline (adding optional fields with defaults to a Pydantic model doesn't change any existing behavior).

- [ ] **Step 6: Commit**

```bash
git add src/tenderai_bf/agents/graph.py tests/test_state_company_fields.py
git commit -m "feat(agents): add company_id/company_config to TenderAIState"
```

---

## Task 3: Neutralize `classification_embedded` in `parse_pdf_structured.py`

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/parse_pdf_structured.py`
- Test: `tests/nodes/test_extraction.py` (check for assertions on removed fields first)

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_quotidien_structured()` output items with structural fields only — no `is_relevant`/`relevance_score`/`domain`/`classification_embedded`/`classification_method`/`category`/`is_results_notice` change (see below — `is_results_notice` is KEPT, it's a structural signal, not a relevance judgment).

- [ ] **Step 1: Check for existing tests asserting on removed fields**

Run: `grep -n "domain\|is_relevant\|classification_embedded\|relevance_score" tests/nodes/test_extraction.py`
If any test asserts on these fields for quotidien/PDF-structured extraction specifically, note them — Step 6 below updates any that break.

- [ ] **Step 2: Write the failing test**

Add to `tests/nodes/test_extraction.py` (or create it if it doesn't already cover this — check first):
```python
def test_parse_quotidien_structured_no_relevance_fields():
    """Structural extraction only — no relevance judgment embedded."""
    from unittest.mock import MagicMock, patch
    from tenderai_bf.agents.nodes.parse_pdf_structured import TenderBlock

    # TenderBlock itself must no longer accept is_relevant/domain/relevance_score
    block_fields = TenderBlock.model_fields.keys()
    assert "is_relevant" not in block_fields
    assert "domain" not in block_fields
    assert "relevance_score" not in block_fields
    assert "is_results_notice" in block_fields  # kept — structural signal
```

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov -k no_relevance_fields`
Expected: FAIL — `is_relevant`/`domain`/`relevance_score` are still present on `TenderBlock`

- [ ] **Step 4: Trim `TenderBlock` schema**

Current (`parse_pdf_structured.py:49-98`):
```python
class TenderBlock(BaseModel):
    """Extraction + classification result for a single quotidien notice."""

    entity: str = Field(default="Inconnu", description="Entité émettrice de l'avis")
    reference: str = Field(
        default="Inconnu",
        description="Numéro de référence (ex: N°2026-001/MINEFID/SG/DPCL)",
    )
    tender_object: str = Field(
        default="Inconnu", description="Objet de l'appel d'offres"
    )
    deadline: str | None = Field(
        default=None, description="Date limite au format DD-MM-YYYY"
    )
    description: str = Field(
        default="", description="Description du marché (300 mots maximum)"
    )
    budget: str | None = Field(
        default=None, description="Montant estimé si mentionné (ex: 50 000 000 FCFA)"
    )
    location: str | None = Field(
        default=None, description="Localisation géographique si mentionnée"
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si cet avis est un PV de dépouillement, résultat d'attribution, "
            "prorogation, rectificatif ou annulation — pas un appel actif ouvert"
        ),
    )
    is_relevant: bool = Field(
        default=False,
        description=(
            "True si pertinent pour YULCOM (IT services, matériel informatique, conseil IT). "
            "False pour tout le reste."
        ),
    )
    domain: Literal[
        "it_services", "it_hardware", "it_consulting", "hors_perimetre"
    ] = Field(
        default="hors_perimetre",
        description="Domaine : it_services, it_hardware, it_consulting, ou hors_perimetre",
    )
    relevance_score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Score de pertinence 1-5 : 5=cœur de métier YULCOM, 3=pertinent, 1=hors périmètre",
    )
```

Replace with:
```python
class TenderBlock(BaseModel):
    """Structural extraction result for a single quotidien notice.

    No relevance judgment — classify_node (delivery graph) is the sole place
    relevance is decided, per-company.
    """

    entity: str = Field(default="Inconnu", description="Entité émettrice de l'avis")
    reference: str = Field(
        default="Inconnu",
        description="Numéro de référence (ex: N°2026-001/MINEFID/SG/DPCL)",
    )
    tender_object: str = Field(
        default="Inconnu", description="Objet de l'appel d'offres"
    )
    deadline: str | None = Field(
        default=None, description="Date limite au format DD-MM-YYYY"
    )
    description: str = Field(
        default="", description="Description du marché (300 mots maximum)"
    )
    budget: str | None = Field(
        default=None, description="Montant estimé si mentionné (ex: 50 000 000 FCFA)"
    )
    location: str | None = Field(
        default=None, description="Localisation géographique si mentionnée"
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si cet avis est un PV de dépouillement, résultat d'attribution, "
            "prorogation, rectificatif ou annulation — pas un appel actif ouvert"
        ),
    )
```

Note `Literal` import at the top of the file (`from typing import Literal`) becomes unused — remove it (check `grep -n "Literal" src/tenderai_bf/agents/nodes/parse_pdf_structured.py` shows no other use).

- [ ] **Step 5: Trim `_EXTRACTION_PROMPT`**

Current prompt (`parse_pdf_structured.py:104-150`) asks the LLM to judge `is_relevant`/`domain`/`relevance_score` against "DOMAINES IT de YULCOM". Replace the full prompt body:

```python
_EXTRACTION_PROMPT = """\
Tu es un expert en marchés publics du Burkina Faso. Extrait TOUS les avis contenus \
dans ce texte du Quotidien des Marchés Publics (DGCMEF). Ne manque aucun avis.

TEXTE DU DOCUMENT :
{document_text}

Pour chaque avis trouvé, remplis les champs structurels ci-dessous.

RÈGLE :
- is_results_notice = true pour : PV de dépouillement, résultats d'attribution, annulations, \
prorogations, rectificatifs (tout ce qui n'est pas un appel actif ouvert)

Retournez UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
{{
  "tenders": [
    {{
      "entity": "Nom de l'organisation",
      "reference": "N°2026-XXX/...",
      "tender_object": "Objet de l'avis",
      "deadline": null,
      "description": "Description courte (200 mots max)",
      "budget": null,
      "location": null,
      "is_results_notice": false
    }}
  ]
}}\
"""
```

- [ ] **Step 6: Trim output dict construction and update docstrings**

Current (`parse_pdf_structured.py:266-297`):
```python
    results = []
    for i, tender in enumerate(tenders):
        is_actionable = tender.is_relevant and not tender.is_results_notice

        item = {
            "id": str(uuid.uuid4()),
            "url": source_url,
            "content_hash": hashlib.sha256(
                f"{tender.reference}:{tender.tender_object}".encode()
            ).hexdigest(),
            "source_type": "quotidien_pdf",
            "quotidien_title": quotidien_title,
            "published_at": datetime.utcnow().isoformat(),
            "location": tender.location or "Burkina Faso",
            # Extracted fields
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "tender_object": tender.tender_object,
            "title": tender.tender_object,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "budget": tender.budget,
            "category": tender.domain,
            # Embedded classification — classify_node passes these through unchanged
            "classification_embedded": True,
            "is_relevant": is_actionable,
            "is_results_notice": tender.is_results_notice,
            "domain": tender.domain,
            # Normalize 1-5 to 0.0-1.0 for downstream score compatibility
            "relevance_score": tender.relevance_score / 5.0,
            "classification_method": "llm_single_pass_extraction",
        }
        results.append(item)

        logger.info(
            f"Notice {i + 1}/{len(tenders)}",
            ref=tender.reference,
            entity=(tender.entity or "")[:50],
            is_relevant=tender.is_relevant,
            is_results_notice=tender.is_results_notice,
            domain=tender.domain,
            score=tender.relevance_score,
        )

    relevant_count = sum(1 for r in results if r["is_relevant"])
    logger.info(
        "Quotidien extraction complete",
        total_notices=len(results),
        relevant=relevant_count,
        results_notices=len(results) - relevant_count,
        run_id=run_id,
    )
    return results
```

Replace with:
```python
    results = []
    for i, tender in enumerate(tenders):
        item = {
            "id": str(uuid.uuid4()),
            "url": source_url,
            "content_hash": hashlib.sha256(
                f"{tender.reference}:{tender.tender_object}".encode()
            ).hexdigest(),
            "source_type": "quotidien_pdf",
            "quotidien_title": quotidien_title,
            "published_at": datetime.utcnow().isoformat(),
            "location": tender.location or "Burkina Faso",
            # Extracted fields
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "tender_object": tender.tender_object,
            "title": tender.tender_object,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "budget": tender.budget,
            "is_results_notice": tender.is_results_notice,
        }
        results.append(item)

        logger.info(
            f"Notice {i + 1}/{len(tenders)}",
            ref=tender.reference,
            entity=(tender.entity or "")[:50],
            is_results_notice=tender.is_results_notice,
        )

    logger.info(
        "Quotidien extraction complete",
        total_notices=len(results),
        run_id=run_id,
    )
    return results
```

Update the module and function docstrings (lines 1-12 and the `parse_quotidien_structured` docstring's Step 4/final line) to remove references to "embedded domain classification" / "classification_embedded=True so classify_node skips them" — this function no longer embeds classification. Replace the module docstring's last paragraph:
```python
"""Structured PDF parser for DGCMEF Quotidien des Marchés Publics.

Strategy: extract the full PDF text with pdfminer, locate the open-tender
section (best-effort, multiple fallback markers), then send it in ONE LLM call.
The LLM extracts all notices' structural fields simultaneously — no relevance
judgment (that happens later, per-company, in the delivery graph's classify step).

This eliminates regex-based block splitting entirely — the approach is robust
to day-to-day formatting changes in the Quotidien publication.

Fallback when AVIS section is not locatable: send the full document.
The LLM uses is_results_notice=True to mark attribution results, which the
pipeline filters out just like explicitly skipped content.
"""
```
And the `parse_quotidien_structured` docstring (currently lines ~220-232):
```python
    """Parse quotidien PDF with a single LLM call that extracts all notices at once.

    1. Extract full PDF text (pdfminer — fast, no OCR overhead for text PDFs)
    2. Locate the open-tender section (multiple fallback markers; sends full doc if none match)
    3. One LLM call → TenderList with all notices' structural fields

    Args:
        llm_cfg: LLM configuration dict (from state.country_config["llm"]).
    """
```

- [ ] **Step 7: Thread `source_name` through this pathway (needed by `persist_notices`, Task 8)**

Verified directly against `main` while writing this plan: quotidien PDF items never carry a `source_name`/`source` field by the time they reach `persist_notices` — `extract_item_links.py:252` sets `source_name` on the original *link* dict, but `fetch_items.py`'s quotidien-PDF branch drops it when building its own item dict, and `parse_quotidien_structured()` never receives or re-attaches it. Without this fix, DGCMEF quotidien items — the primary source for Burkina Faso — would hit `persist_notices`' skip-with-warning fallback on every single run whenever a country has more than one configured source (the common case), since neither of the fallback chain's first two tiers has anything to match against.

**3a.** In `src/tenderai_bf/agents/nodes/fetch_items.py`, the quotidien-PDF item construction:
```python
        # Process quotidien PDFs (already downloaded, no need to fetch)
        for link in quotidien_pdfs:
            items.append(
                {
                    "url": link["url"],
                    "content": link["content"],  # PDF bytes
                    "content_type": "application/pdf",
                    "status": "success",
                    "fetched_at": datetime.utcnow().isoformat(),
                    "size": len(link["content"]),
                    "parser_type": "pdf_quotidien",
                    "type": "quotidien_pdf",
                    "title": link.get("title", "Quotidien"),
                    "filename": link.get("filename", "quotidien.pdf"),
                }
            )
```
becomes (adding `source_name`, matching the exact pattern already used for `rag_pdfs` a few lines below this block):
```python
        # Process quotidien PDFs (already downloaded, no need to fetch)
        for link in quotidien_pdfs:
            items.append(
                {
                    "url": link["url"],
                    "content": link["content"],  # PDF bytes
                    "content_type": "application/pdf",
                    "status": "success",
                    "fetched_at": datetime.utcnow().isoformat(),
                    "size": len(link["content"]),
                    "parser_type": "pdf_quotidien",
                    "type": "quotidien_pdf",
                    "title": link.get("title", "Quotidien"),
                    "filename": link.get("filename", "quotidien.pdf"),
                    "source_name": link.get("source_name", "Unknown"),
                }
            )
```

**3b.** In `src/tenderai_bf/agents/nodes/parse_extract.py`, the call site (verify exact current line numbers with `grep -n "parse_quotidien_structured(" src/tenderai_bf/agents/nodes/parse_extract.py` — this task doesn't otherwise touch this file, so line numbers should match what was read while writing this plan, but confirm before editing):
```python
                    quotidien_tenders = parse_quotidien_structured(
                        pdf_content=content,
                        source_url=item["url"],
                        quotidien_title=item.get(
                            "title", "Quotidien des Marchés Publics"
                        ),
                        run_id=state.run_id,
                        llm_cfg=state.country_config.get("llm", {}),
                    )
```
becomes:
```python
                    quotidien_tenders = parse_quotidien_structured(
                        pdf_content=content,
                        source_url=item["url"],
                        quotidien_title=item.get(
                            "title", "Quotidien des Marchés Publics"
                        ),
                        source_name=item.get("source_name", "Unknown"),
                        run_id=state.run_id,
                        llm_cfg=state.country_config.get("llm", {}),
                    )
```

**3c.** In `src/tenderai_bf/agents/nodes/parse_pdf_structured.py`, add `source_name` to `parse_quotidien_structured()`'s signature and output dict. Current signature:
```python
def parse_quotidien_structured(
    pdf_content: bytes,
    source_url: str,
    quotidien_title: str,
    run_id: str,
    llm_cfg: dict | None = None,
) -> list[dict]:
```
becomes:
```python
def parse_quotidien_structured(
    pdf_content: bytes,
    source_url: str,
    quotidien_title: str,
    run_id: str,
    source_name: str = "Unknown",
    llm_cfg: dict | None = None,
) -> list[dict]:
```
And in the output dict construction (from Step 6 above), add `"source_name": source_name,` alongside the other fields:
```python
        item = {
            "id": str(uuid.uuid4()),
            "url": source_url,
            "content_hash": hashlib.sha256(
                f"{tender.reference}:{tender.tender_object}".encode()
            ).hexdigest(),
            "source_type": "quotidien_pdf",
            "source_name": source_name,
            "quotidien_title": quotidien_title,
            "published_at": datetime.utcnow().isoformat(),
            "location": tender.location or "Burkina Faso",
            # Extracted fields
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "tender_object": tender.tender_object,
            "title": tender.tender_object,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "budget": tender.budget,
            "is_results_notice": tender.is_results_notice,
        }
```

Add a test confirming this, appended to `tests/nodes/test_extraction.py`:
```python
def test_parse_quotidien_structured_carries_source_name():
    import inspect
    from tenderai_bf.agents.nodes.parse_pdf_structured import parse_quotidien_structured

    params = inspect.signature(parse_quotidien_structured).parameters
    assert "source_name" in params
```

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov -k carries_source_name`
Expected: PASS after the above changes.

- [ ] **Step 8: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov`
Expected: PASS. If any pre-existing test in this file asserted on `domain`/`is_relevant`/`relevance_score`/`classification_embedded` output from `parse_quotidien_structured`, update those assertions to match the new structural-only output (remove the assertion, or assert the key is absent — do not invent new relevance-related test cases here).

- [ ] **Step 9: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond the pre-task baseline.

- [ ] **Step 10: Commit**

```bash
git add src/tenderai_bf/agents/nodes/parse_pdf_structured.py src/tenderai_bf/agents/nodes/parse_extract.py src/tenderai_bf/agents/nodes/fetch_items.py tests/nodes/test_extraction.py
git commit -m "fix(pipeline): strip relevance judgment from quotidien PDF structured extraction

TenderBlock/the extraction prompt no longer request is_relevant/domain/
relevance_score — structural fields only. classify_node (delivery graph)
becomes the sole place relevance is decided, per company.

Also threads source_name through fetch_items.py -> parse_extract.py ->
parse_quotidien_structured() (it existed on the link dict but was
dropped before reaching this pathway's output) — persist_notices (Task 8)
needs it to resolve which Source row a quotidien item came from, and
without it the DGCMEF pathway would hit persist_notices' skip-with-warning
fallback on every run for any country with more than one configured source."
```

---

## Task 4: Neutralize `classification_embedded` in `parse_tavily_listing.py`

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/parse_tavily_listing.py`
- Test: `tests/nodes/test_extraction.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_tavily_listing()` output items with structural fields only, same pattern as Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/nodes/test_extraction.py`:
```python
def test_parse_tavily_listing_no_relevance_fields():
    from tenderai_bf.agents.nodes.parse_tavily_listing import TenderItem

    item_fields = TenderItem.model_fields.keys()
    assert "is_relevant" not in item_fields
    assert "domain" not in item_fields
    assert "relevance_score" not in item_fields
    assert "is_results_notice" in item_fields  # kept — structural signal
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov -k tavily_listing_no_relevance`
Expected: FAIL

- [ ] **Step 3: Trim `TenderItem` schema**

Current (`parse_tavily_listing.py:29-71`):
```python
class TenderItem(BaseModel):
    """A single tender notice extracted from a listing page."""

    title: str = Field(default="", description="Titre / objet de l'appel d'offres")
    entity: str = Field(default="", description="Entité ou organisme émetteur")
    reference: str = Field(default="", description="Numéro de référence si présent")
    deadline: str | None = Field(
        default=None,
        description="Date limite de soumission au format YYYY-MM-DD ou DD-MM-YYYY si disponible",
    )
    description: str = Field(
        default="", description="Description courte (150 mots max)"
    )
    tender_url: str | None = Field(
        default=None,
        description="URL directe vers la fiche de l'appel d'offres si visible dans le texte",
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si c'est un résultat d'attribution, PV de dépouillement, "
            "contrat déjà octroyé — pas un appel ouvert"
        ),
    )
    is_relevant: bool = Field(
        default=False,
        description=(
            "True uniquement si l'objet concerne les domaines IT de YULCOM : "
            "services IT, matériel informatique ou conseil/ingénierie IT"
        ),
    )
    domain: Literal[
        "it_services", "it_hardware", "it_consulting", "hors_perimetre"
    ] = Field(
        default="hors_perimetre",
        description="Domaine IT ou hors_perimetre",
    )
    relevance_score: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Score 1-5 : 5=cœur de métier YULCOM, 3=pertinent, 1=hors périmètre",
    )
```

Replace with:
```python
class TenderItem(BaseModel):
    """A single tender notice's structural fields, extracted from a listing page.

    No relevance judgment — classify_node (delivery graph) is the sole place
    relevance is decided, per-company.
    """

    title: str = Field(default="", description="Titre / objet de l'appel d'offres")
    entity: str = Field(default="", description="Entité ou organisme émetteur")
    reference: str = Field(default="", description="Numéro de référence si présent")
    deadline: str | None = Field(
        default=None,
        description="Date limite de soumission au format YYYY-MM-DD ou DD-MM-YYYY si disponible",
    )
    description: str = Field(
        default="", description="Description courte (150 mots max)"
    )
    tender_url: str | None = Field(
        default=None,
        description="URL directe vers la fiche de l'appel d'offres si visible dans le texte",
    )
    is_results_notice: bool = Field(
        default=False,
        description=(
            "True si c'est un résultat d'attribution, PV de dépouillement, "
            "contrat déjà octroyé — pas un appel ouvert"
        ),
    )
```

Remove the now-unused `from typing import Literal` import (verify with `grep -n "Literal" src/tenderai_bf/agents/nodes/parse_tavily_listing.py`).

- [ ] **Step 4: Trim `_EXTRACTION_PROMPT`**

Current prompt body (`parse_tavily_listing.py:76-136`) asks for `is_relevant`/`domain`/`relevance_score` per YULCOM's IT domains. Replace the full prompt:

```python
_EXTRACTION_PROMPT = """\
Tu es un expert en marchés publics. Tu reçois le contenu textuel d'une page de \
listing d'appels d'offres (portail gouvernemental, organisation internationale, etc.).

TEXTE DE LA PAGE :
{page_text}

SOURCE : {source_name}
URL_DE_BASE : {source_url}

Ta mission :
1. Identifier TOUS les appels d'offres listés dans ce texte (même partiellement).
2. Pour chaque appel d'offres, extraire les informations disponibles.

RÈGLES :
- is_results_notice = true pour contrats déjà octroyés, résultats d'appels d'offres, \
PV de dépouillement
- Si la page ne contient aucun appel d'offres identifiable, retourne une liste vide.
- N'invente pas d'informations absentes du texte.
- Pour tender_url : le texte peut contenir des liens au format [Titre](/chemin/vers/fiche). \
Extrais le chemin (ex: /fr/occasions-de-marche/appels-d-offres/ID) pour chaque appel. \
Si le chemin est relatif (commence par /), le retourner tel quel — il sera rendu absolu \
automatiquement avec l'URL_DE_BASE fournie. Si l'URL complète est visible, l'utiliser directement.

Retourne UNIQUEMENT du JSON valide (pas de markdown, pas d'explication) :
{{
  "tenders": [
    {{
      "title": "Titre de l'appel d'offres",
      "entity": "Organisation émettrice",
      "reference": "",
      "deadline": null,
      "description": "Description courte",
      "tender_url": "/chemin/vers/fiche-ou-null",
      "is_results_notice": false
    }}
  ]
}}\
"""
```

- [ ] **Step 5: Check `_normalize_tender_dict` for now-dead clamping logic**

Read `parse_tavily_listing.py`'s `_normalize_tender_dict` function (the one right after `_EXTRACTION_PROMPT`, described in its own docstring as "Clamp/normalize LLM output before Pydantic validation... relevance_score > 5 or domain values outside"). If it clamps/normalizes `relevance_score`/`domain` fields specifically, remove that clamping logic for the now-removed fields (keep any clamping for fields still on `TenderItem`, e.g. any title/description length limits it may also apply — read the function in full before editing to distinguish what's field-specific vs generic).

- [ ] **Step 6: Trim output dict construction**

Current (`parse_tavily_listing.py:253-300`):
```python
    results = []
    for i, tender in enumerate(tenders):
        is_actionable = tender.is_relevant and not tender.is_results_notice

        # Resolve tender URL: make relative paths absolute, fall back to source listing URL
        raw_url = tender.tender_url
        if raw_url:
            if raw_url.startswith("/"):
                raw_url = _base_origin + raw_url
            elif not raw_url.startswith("http"):
                from urllib.parse import urljoin
                raw_url = urljoin(source_url, raw_url)
        item_url = raw_url or source_url

        item = {
            "id": str(uuid.uuid4()),
            "url": item_url,
            "source_url": source_url,
            "content_hash": hashlib.sha256(
                f"{source_name}:{tender.reference}:{tender.title}".encode()
            ).hexdigest(),
            "source_type": "tavily_listing",
            "source_name": source_name,
            "published_at": datetime.utcnow().isoformat(),
            # Extracted fields
            "title": tender.title,
            "tender_object": tender.title,
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "category": tender.domain,
            # Embedded classification — classify_node passes these through
            "classification_embedded": True,
            "is_relevant": is_actionable,
            "is_results_notice": tender.is_results_notice,
            "domain": tender.domain,
            "relevance_score": tender.relevance_score / 5.0,
            "classification_method": "llm_tavily_listing_extraction",
        }
        results.append(item)

        logger.info(
            f"Listing item {i + 1}/{len(tenders)}",
            source=source_name,
            title=(tender.title or "")[:80],
            entity=(tender.entity or "")[:50],
            is_relevant=tender.is_relevant,
            domain=tender.domain,
            score=tender.relevance_score,
```

Replace with (note: `source_name` field is KEPT — it's a structural provenance field, used by `persist_notices` in Task 8, not a relevance signal):
```python
    results = []
    for i, tender in enumerate(tenders):
        # Resolve tender URL: make relative paths absolute, fall back to source listing URL
        raw_url = tender.tender_url
        if raw_url:
            if raw_url.startswith("/"):
                raw_url = _base_origin + raw_url
            elif not raw_url.startswith("http"):
                from urllib.parse import urljoin
                raw_url = urljoin(source_url, raw_url)
        item_url = raw_url or source_url

        item = {
            "id": str(uuid.uuid4()),
            "url": item_url,
            "source_url": source_url,
            "content_hash": hashlib.sha256(
                f"{source_name}:{tender.reference}:{tender.title}".encode()
            ).hexdigest(),
            "source_type": "tavily_listing",
            "source_name": source_name,
            "published_at": datetime.utcnow().isoformat(),
            # Extracted fields
            "title": tender.title,
            "tender_object": tender.title,
            "entity": tender.entity,
            "reference": tender.reference,
            "ref_no": tender.reference,
            "deadline": tender.deadline,
            "deadline_at": tender.deadline,
            "description": tender.description,
            "is_results_notice": tender.is_results_notice,
        }
        results.append(item)

        logger.info(
            f"Listing item {i + 1}/{len(tenders)}",
            source=source_name,
            title=(tender.title or "")[:80],
            entity=(tender.entity or "")[:50],
```

(Leave the closing `)` and remainder of that `logger.info(...)` call — it has more fields after `score=tender.relevance_score`; check the file and remove only the now-invalid `domain=`/`score=` kwargs, keep any others like `run_id=run_id` that follow.)

Update the module docstring (lines 1-8):
```python
"""Extract individual tender notices from a Tavily-extracted listing page.

Strategy: one LLM call that receives the raw page text and returns all tender
notices' structural fields.  This mirrors the approach used by
parse_pdf_structured for DGCMEF quotidien PDFs.

Relevance is judged later, per-company, by classify_node in the delivery graph.
"""
```
And the `parse_tavily_listing` function's own docstring (currently mentions "embeds domain classification... classify_node passes them through without re-classifying") — update similarly to say structural-only extraction.

- [ ] **Step 7: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov`
Expected: PASS, update any pre-existing assertions on removed fields per Task 3's Step 7 pattern.

- [ ] **Step 8: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline.

- [ ] **Step 9: Commit**

```bash
git add src/tenderai_bf/agents/nodes/parse_tavily_listing.py tests/nodes/test_extraction.py
git commit -m "fix(pipeline): strip relevance judgment from Tavily listing extraction

TenderItem/the extraction prompt no longer request is_relevant/domain/
relevance_score — structural fields only, same treatment as
parse_pdf_structured.py."
```

---

## Task 5: Neutralize `classification_embedded` in the Le Devoir pathway

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/fetch_ledevoir.py`
- Modify: `src/tenderai_bf/agents/nodes/fetch_items.py:319-336` (ledevoir items block)
- Modify: `src/tenderai_bf/agents/nodes/parse_extract.py:600-624` (ledevoir branch)

**Interfaces:**
- Consumes: nothing new.
- Produces: Le Devoir pathway output items with structural fields only.

**Note:** the design spec's own file list only named `parse_extract.py`/`parse_pdf_structured.py`/`parse_tavily_listing.py` for this — verified directly (not assumed) that the Le Devoir pathway's actual relevance judgment originates in `fetch_ledevoir.py`'s OCR prompt, not in `parse_extract.py` (which only relays the value). This task closes that gap the spec's file list missed.

- [ ] **Step 1: Write the failing test**

Add to `tests/nodes/test_extraction.py` (or a new `tests/nodes/test_fetch_ledevoir.py` if one doesn't exist — check with `ls tests/nodes/ | grep ledevoir` first):
```python
def test_ledevoir_ocr_prompt_has_no_relevance_field():
    from tenderai_bf.agents.nodes.fetch_ledevoir import _OCR_PROMPT

    assert "is_relevant" not in _OCR_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov -k ledevoir_ocr_prompt`
Expected: FAIL

- [ ] **Step 3: Trim `_OCR_PROMPT` in `fetch_ledevoir.py`**

Current:
```python
_OCR_PROMPT = """\
Ce scan est une page de journal contenant des avis légaux et appels d'offres publiés au Québec.

Extrais TOUS les appels d'offres et avis de marchés publics que tu vois sur cette image.
Pour chaque appel d'offres trouvé, retourne un objet JSON avec :
- "title": intitulé de l'appel d'offres
- "entity": organisme qui publie l'appel d'offres
- "reference": numéro de référence si présent
- "deadline": date limite de soumission (format YYYY-MM-DD si possible)
- "description": description courte de l'objet du marché (2-3 phrases)
- "is_relevant": true si l'appel d'offres concerne l'informatique, les services numériques, le matériel informatique ou le conseil IT ; false sinon

Retourne UNIQUEMENT un JSON valide de la forme :
{"tenders": [...]}

Si tu ne vois aucun appel d'offres ou avis de marché public sur cette image, retourne {"tenders": []}.\
"""
```

Replace with:
```python
_OCR_PROMPT = """\
Ce scan est une page de journal contenant des avis légaux et appels d'offres publiés au Québec.

Extrais TOUS les appels d'offres et avis de marchés publics que tu vois sur cette image.
Pour chaque appel d'offres trouvé, retourne un objet JSON avec :
- "title": intitulé de l'appel d'offres
- "entity": organisme qui publie l'appel d'offres
- "reference": numéro de référence si présent
- "deadline": date limite de soumission (format YYYY-MM-DD si possible)
- "description": description courte de l'objet du marché (2-3 phrases)

Retourne UNIQUEMENT un JSON valide de la forme :
{"tenders": [...]}

Si tu ne vois aucun appel d'offres ou avis de marché public sur cette image, retourne {"tenders": []}.\
"""
```

- [ ] **Step 4: Remove `is_relevant` from `fetch_ledevoir()`'s normalized output**

Current (near the end of `fetch_ledevoir()`):
```python
        normalized = [
            {
                "url": n.get("source_image_url", _LISTING_URL),
                "content": n.get("description", ""),
                "title": n.get("title", ""),
                "entity": n.get("entity", ""),
                "reference": n.get("reference", ""),
                "deadline": n.get("deadline"),
                "is_relevant": n.get("is_relevant", False),
                "score": None,
                "source": "ledevoir",
            }
            for n in all_notices
        ]
```

Replace with:
```python
        normalized = [
            {
                "url": n.get("source_image_url", _LISTING_URL),
                "content": n.get("description", ""),
                "title": n.get("title", ""),
                "entity": n.get("entity", ""),
                "reference": n.get("reference", ""),
                "deadline": n.get("deadline"),
                "score": None,
                "source": "ledevoir",
            }
            for n in all_notices
        ]
```

- [ ] **Step 5: Remove `is_relevant` from `fetch_items.py`'s ledevoir items block**

Current (`fetch_items.py`, "Le Devoir items — OCR already done at fetch stage, pass through with embedded classification"):
```python
        # Le Devoir items — OCR already done at fetch stage, pass through with embedded classification
        for link in ledevoir_items:
            items.append({
                "url": link.get("url", "https://www.ledevoir.com/services-et-annonces/avis-publics"),
                "content": link.get("description", link.get("content", "")),
                "status": "success",
                "fetched_at": datetime.utcnow().isoformat(),
                "parser_type": "ledevoir",
                "source": "ledevoir",
                "title": link.get("title", ""),
                "entity": link.get("entity", ""),
                "reference": link.get("reference", ""),
                "deadline": link.get("deadline"),
                "is_relevant": link.get("is_relevant", False),
            })
```

Replace with:
```python
        # Le Devoir items — OCR already done at fetch stage, structural fields only
        for link in ledevoir_items:
            items.append({
                "url": link.get("url", "https://www.ledevoir.com/services-et-annonces/avis-publics"),
                "content": link.get("description", link.get("content", "")),
                "status": "success",
                "fetched_at": datetime.utcnow().isoformat(),
                "parser_type": "ledevoir",
                "source": "ledevoir",
                "title": link.get("title", ""),
                "entity": link.get("entity", ""),
                "reference": link.get("reference", ""),
                "deadline": link.get("deadline"),
            })
```

- [ ] **Step 6: Trim `parse_extract.py`'s ledevoir branch**

Current (`parse_extract.py:600-624`):
```python
            # Handle Le Devoir notices — OCR + classification already done at fetch stage
            elif parser_type == "ledevoir":
                is_relevant = item.get("is_relevant", False)
                parsed_items.append(
                    {
                        "id": str(uuid.uuid4()),
                        "url": item["url"],
                        "content_hash": content_hash,
                        "title": item.get("title", ""),
                        "tender_object": item.get("title", ""),
                        "entity": item.get("entity", ""),
                        "reference": item.get("reference", ""),
                        "ref_no": item.get("reference", ""),
                        "description": item.get("content", ""),
                        "deadline_at": item.get("deadline"),
                        "category": "it_services" if is_relevant else "hors_perimetre",
                        "source": "ledevoir",
                        "source_type": "ledevoir",
                        # Embedded classification — classify_node passes through
                        "classification_embedded": True,
                        "is_relevant": is_relevant,
                        "relevance_score": 0.8 if is_relevant else 0.1,
                        "classification_method": "groq_vision_ocr",
                    }
                )
                continue
```

Replace with:
```python
            # Handle Le Devoir notices — structural fields only (OCR'd at fetch stage)
            elif parser_type == "ledevoir":
                parsed_items.append(
                    {
                        "id": str(uuid.uuid4()),
                        "url": item["url"],
                        "content_hash": content_hash,
                        "title": item.get("title", ""),
                        "tender_object": item.get("title", ""),
                        "entity": item.get("entity", ""),
                        "reference": item.get("reference", ""),
                        "ref_no": item.get("reference", ""),
                        "description": item.get("content", ""),
                        "deadline_at": item.get("deadline"),
                        "source": "ledevoir",
                        "source_type": "ledevoir",
                    }
                )
                continue
```

- [ ] **Step 7: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_extraction.py -v --no-cov`
Expected: PASS.

- [ ] **Step 8: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline.

- [ ] **Step 9: Commit**

```bash
git add src/tenderai_bf/agents/nodes/fetch_ledevoir.py src/tenderai_bf/agents/nodes/fetch_items.py src/tenderai_bf/agents/nodes/parse_extract.py tests/nodes/test_extraction.py
git commit -m "fix(pipeline): strip relevance judgment from Le Devoir OCR pathway

fetch_ledevoir.py's OCR prompt no longer requests is_relevant — the actual
source of relevance judgment for this pathway, which parse_extract.py's
ledevoir branch only relayed. Closes a gap the design spec's own file list
(parse_extract/parse_pdf_structured/parse_tavily_listing) missed."
```

---

## Task 6: `classify.py` — remove `classification_embedded` handling, rescope to `company_cfg`

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/classify.py`
- Test: `tests/nodes/test_classify.py`

**Interfaces:**
- Consumes: `company_cfg()` (Task 1), `TenderAIState.company_id`/`company_config` (Task 2).
- Produces: `classify_with_keywords(state)`/`classify_with_llm(state)` now read classification config via `company_cfg(state, "classification", ...)` instead of `cfg(state, "pipeline"/"classification", ...)`. Still sets `state.relevant_items` (unchanged field name/shape) — CompanyNoticeStatus writing is added separately in Task 11, not here, so this task stays testable without a DB fixture.

- [ ] **Step 1: Write the failing test**

Read `tests/nodes/test_classify.py` in full first (both the legacy `MockState` section and the newer `TenderAIState` section) — this task rewrites both. Replace the entire file content (the legacy section's `MockState.country_config` moves its `classification` section to a new `company_config`, keeping `llm` under `country_config`; the newer section does the same):

```python
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


_MOCK_COUNTRY_CONFIG = {
    "llm": {
        "provider": "groq", "groq_model": "llama-3.3-70b-versatile",
        "openai_model": "gpt-4o", "ollama_model": "llama3", "ollama_base_url": "",
        "temperature": 0.1, "max_tokens": 2000, "timeout": 60,
    },
}

_MOCK_COMPANY_CONFIG = {
    "classification": {
        "min_relevance_score": 0.3,
        "relevant_keywords": {
            "it_services": [
                "informatique", "logiciel", "réseau", "serveur", "ordinateur",
                "internet", "site web", "application", "base de données",
                "cybersécurité", "cloud", "données", "numérique", "digital",
                "ERP", "CRM", "SIG", "GIS", "télécommunication", "fibre optique",
            ],
        },
    },
}


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
            self.country_id = 0
            self.country_config = _MOCK_COUNTRY_CONFIG
            self.company_id = 0
            self.company_config = _MOCK_COMPANY_CONFIG

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
            self.country_id = 0
            self.country_config = _MOCK_COUNTRY_CONFIG
            self.company_id = 0
            self.company_config = _MOCK_COMPANY_CONFIG

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


# ---------------------------------------------------------------------------
# DB-first company_cfg() tests — use TenderAIState, not MockState
# ---------------------------------------------------------------------------

import os

os.environ.setdefault("TENDERAI_ENVIRONMENT", "test")
os.environ.setdefault("TENDERAI_DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from tenderai_bf.agents.graph import TenderAIState  # noqa: E402

COMPANY_CONFIG_CLASSIFY = {
    "classification": {
        "min_relevance_score": 0.3,
        "relevant_keywords": {
            "it_services": ["informatique", "logiciel", "serveur", "réseau"],
        },
    },
}

COUNTRY_CONFIG_CLASSIFY = {
    "llm": {
        "provider": "groq", "groq_model": "llama-3.3-70b-versatile",
        "openai_model": "gpt-4o", "ollama_model": "llama3", "ollama_base_url": "",
        "temperature": 0.1, "max_tokens": 2000, "timeout": 60,
    },
}


def test_classify_with_keywords_uses_company_config():
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {"id": "t1", "title": "Acquisition de serveurs et réseau",
             "description": "Fourniture de serveurs", "category": "IT",
             "entity": "Ministère", "keywords": []},
            {"id": "t2", "title": "Construction de routes rurales",
             "description": "Travaux BTP", "category": "BTP",
             "entity": "Mairie", "keywords": []},
        ],
    )
    result = classify_with_keywords(state)
    relevant_ids = [i["id"] for i in result.relevant_items]
    assert "t1" in relevant_ids
    assert "t2" not in relevant_ids


def test_classify_fails_hard_if_company_config_missing():
    import pytest
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config={},
        items_parsed=[{"id": "t1", "title": "test", "description": "x",
                       "category": "IT", "entity": "X", "keywords": []}],
    )
    with pytest.raises(RuntimeError, match="Missing DB config: company_id=1"):
        classify_with_keywords(state)


def test_classify_no_longer_reads_classification_embedded():
    """Neutralization: an item with classification_embedded=True must go
    through the normal keyword path, not bypass it."""
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {
                "id": "t3",
                "title": "Construction de routes rurales",
                "description": "Travaux BTP, aucun rapport avec l'informatique",
                "category": "BTP",
                "entity": "Mairie",
                "keywords": [],
                # Pre-neutralization, this field would have made classify_node
                # pass the item through as relevant unconditionally. It must
                # now be ignored entirely.
                "classification_embedded": True,
                "is_relevant": True,
                "relevance_score": 0.9,
            },
        ],
    )
    result = classify_with_keywords(state)
    relevant_ids = [i["id"] for i in result.relevant_items]
    assert "t3" not in relevant_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_classify.py -v --no-cov`
Expected: FAIL — `classify_with_keywords`/`classify_with_llm` still read `cfg(state, "classification", ...)` from `country_config`, which is now empty in the test fixtures; also the `classification_embedded` short-circuit is still present so `test_classify_no_longer_reads_classification_embedded` fails by asserting the opposite of current behavior.

- [ ] **Step 3: Remove the `classification_embedded` branch in `classify_with_keywords`**

Current (`classify.py:449-490`, spanning the branch itself and the now-dead "existing relevance_score" block immediately after it):
```python
            # Items pre-classified by the extraction LLM — pass through directly.
            if item.get("classification_embedded"):
                if item.get("is_relevant") and not item.get("is_results_notice"):
                    # Quality gate: items with no geographic context kept only if genuinely open
                    loc = (item.get("location") or "").strip()
                    has_location = bool(
                        loc
                        and loc.lower()
                        not in ("n/a", "non disponible", "none", "-", "")
                    )
                    if not has_location and not _is_real_open_tender(item):
                        item["relevance_score"] = 0.0
                        item["is_relevant"] = False
                        item["classification_method"] = "quality_filter"
                        logger.debug(
                            "Quality filter: no location + no open deadline, item rejected",
                            item_id=item.get("id"),
                            run_id=state.run_id,
                        )
                    else:
                        relevant_items.append(item)
                else:
                    item["relevance_score"] = item.get("relevance_score", 0.0)
                    item["is_relevant"] = False
                continue

            # Check if item already has relevance_score from extraction
            existing_score = item.get("relevance_score")
            if existing_score is not None:
                min_score = cfg(state, "pipeline", "min_relevance_score")
                if existing_score >= min_score:
                    item["is_relevant"] = True
                    relevant_items.append(item)
                else:
                    item["is_relevant"] = False
                continue
```

(Read the file around these lines first with `grep -n "classification_embedded\|existing_score" src/tenderai_bf/agents/nodes/classify.py` to confirm exact current line numbers and surrounding braces before editing — line numbers may have shifted slightly from earlier tasks' edits to other files, though nothing in Tasks 1-5 touches `classify.py` itself.)

Delete both blocks entirely (the `if item.get("classification_embedded"):` branch and the `existing_score` block immediately after it) — after neutralization (Tasks 3-5), no item ever carries `classification_embedded` or a pre-set `relevance_score`, so both blocks are unreachable dead code. Execution falls through directly from the disqualification filters (geographic/attribution/supplier-registration/expired — unchanged, still run first) straight into the keyword-matching logic that follows.

- [ ] **Step 4: Same removal in `classify_with_llm`**

Current (`classify.py:693-717`, the LLM function's equivalent branch):
```python
            # Items pre-classified by the extraction LLM — pass through directly.
            if item.get("classification_embedded"):
                if item.get("is_relevant") and not item.get("is_results_notice"):
                    relevant_items.append(item)
                else:
                    item["relevance_score"] = item.get("relevance_score", 0.0)
                    item["is_relevant"] = False
                continue
```

Delete this block entirely (verify exact current content/line numbers with `grep -n "classification_embedded" src/tenderai_bf/agents/nodes/classify.py` before editing — the LLM function's branch may be shorter than the keywords function's, without an equivalent "existing_score" dead-code block; only remove what's actually there).

- [ ] **Step 5: Rescope `cfg()` calls to `company_cfg()`**

In both `classify_with_keywords` and `classify_with_llm`, change:
- `cfg(state, "classification", "relevant_keywords")` → `company_cfg(state, "classification", "relevant_keywords")`
- Every `cfg(state, "pipeline", "min_relevance_score")` → `company_cfg(state, "classification", "min_relevance_score")` (note: section changes from `"pipeline"` to `"classification"`, per this plan's Global Constraints — this is the original multi-company spec's explicit instruction, not a new invention).

Leave unchanged: `cfg(state, "pipeline", "use_llm_classification")` (in `classify_node`, dispatches which sub-function to call — this is a harvest/delivery-agnostic pipeline behavior toggle, stays country-scoped) and both `cfg(state, "llm", "provider")` calls (global, per this plan's Global Constraints).

Add the import at the top of the file:
```python
from .._cfg import cfg, company_cfg
```
(replacing whatever the current import line is — check with `grep -n "from \.\._cfg import" src/tenderai_bf/agents/nodes/classify.py`).

- [ ] **Step 6: Update the two country-scoped classify tests in `test_pipeline_country.py`**

Read `tests/test_pipeline_country.py` in full first — it has 7 tests total; only these two test country-scoping of `classify_with_keywords`, which this task changes to company-scoping. The other 5 (`test_tenderai_state_has_country_fields`, `test_run_sets_country_id_on_state`, `test_load_sources_filters_by_country_id`, `test_summarize_uses_country_prompts`, `test_email_report_uses_country_to_address`) are unaffected by this task and must NOT be changed — they test country context loading, source loading, summarization prompts, and email `to_address`, none of which this task touches.

Current:
```python
def test_classify_uses_country_keywords():
    """classify_with_keywords must use state.country_config['classification']['relevant_keywords']."""
    from tenderai_bf.agents.graph import TenderAIState
    from tenderai_bf.agents.nodes.classify import classify_with_keywords

    state = TenderAIState(country_id=1)
    state.country_config = {
        "classification": {"relevant_keywords": {"it": ["informatique", "logiciel"]}},
        "pipeline": {"min_relevance_score": 0.5, "use_llm_classification": False},
    }
    state.items_parsed = [
        {
            "title": "Fourniture de logiciel",
            "description": "Achat logiciel",
            "url": "http://x.com",
        }
    ]

    result = classify_with_keywords(state)
    relevant = [i for i in result.items_parsed if i.get("is_relevant")]
    assert len(relevant) == 1


def test_classify_uses_country_min_relevance_score():
    """Classify must use state.country_config['pipeline']['min_relevance_score']."""
    from tenderai_bf.agents.graph import TenderAIState
    from tenderai_bf.agents.nodes.classify import classify_with_keywords

    state = TenderAIState(country_id=1)
    state.country_config = {
        "classification": {"relevant_keywords": {"all": ["xyz_never_matches"]}},
        "pipeline": {"min_relevance_score": 0.99, "use_llm_classification": False},
    }
    state.items_parsed = [
        {
            "title": "Travaux routiers",
            "description": "Construction route",
            "url": "http://x.com",
        }
    ]

    result = classify_with_keywords(state)
    assert all(not i.get("is_relevant") for i in result.items_parsed)
```

Replace with (renamed to reflect the new scoping; note these assert on `result.items_parsed`, not `result.relevant_items` — `classify_with_keywords` mutates each item dict's `is_relevant` key in place, and `items_parsed`/`relevant_items` reference the same underlying dicts, so checking either list's items shows the same mutation — keep this existing assertion style unchanged, only the config source moves):
```python
def test_classify_uses_company_keywords():
    """classify_with_keywords must use state.company_config['classification']['relevant_keywords']."""
    from tenderai_bf.agents.graph import TenderAIState
    from tenderai_bf.agents.nodes.classify import classify_with_keywords

    state = TenderAIState(country_id=1, company_id=1)
    state.country_config = {"pipeline": {"use_llm_classification": False}}
    state.company_config = {
        "classification": {
            "relevant_keywords": {"it": ["informatique", "logiciel"]},
            "min_relevance_score": 0.5,
        },
    }
    state.items_parsed = [
        {
            "title": "Fourniture de logiciel",
            "description": "Achat logiciel",
            "url": "http://x.com",
        }
    ]

    result = classify_with_keywords(state)
    relevant = [i for i in result.items_parsed if i.get("is_relevant")]
    assert len(relevant) == 1


def test_classify_uses_company_min_relevance_score():
    """Classify must use state.company_config['classification']['min_relevance_score']."""
    from tenderai_bf.agents.graph import TenderAIState
    from tenderai_bf.agents.nodes.classify import classify_with_keywords

    state = TenderAIState(country_id=1, company_id=1)
    state.country_config = {"pipeline": {"use_llm_classification": False}}
    state.company_config = {
        "classification": {
            "relevant_keywords": {"all": ["xyz_never_matches"]},
            "min_relevance_score": 0.99,
        },
    }
    state.items_parsed = [
        {
            "title": "Travaux routiers",
            "description": "Construction route",
            "url": "http://x.com",
        }
    ]

    result = classify_with_keywords(state)
    assert all(not i.get("is_relevant") for i in result.items_parsed)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_classify.py tests/test_pipeline_country.py -v --no-cov`
Expected: PASS (both files — including the legacy `MockState`-based tests in `test_classify.py`, run via pytest's collection of top-level `test_*` functions, and the 5 unmodified tests in `test_pipeline_country.py`).

- [ ] **Step 8: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline (deduplicate/graph/other node tests are untouched by this task).

- [ ] **Step 9: Commit**

```bash
git add src/tenderai_bf/agents/nodes/classify.py tests/nodes/test_classify.py tests/test_pipeline_country.py
git commit -m "fix(pipeline): classify_node no longer honors classification_embedded

Removes the pass-through branch in both classify_with_keywords and
classify_with_llm — every item now goes through uniform keyword/LLM
matching. Classification config moves from cfg(country) to
company_cfg(company); min_relevance_score moves from
CountrySettings['pipeline'] to CompanySettings['classification'] per
the original multi-company spec. Updates the two tests in
test_pipeline_country.py that tested the old country-scoped behavior."
```

---

## Task 7: Fix `deduplicate.py` to read `items_parsed`, not `relevant_items`

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/deduplicate.py`
- Test: `tests/nodes/test_deduplicate.py`

**Interfaces:**
- Consumes: `state.items_parsed` (was: `state.relevant_items`, which the harvest graph will never populate once `classify` moves entirely to delivery — Task 9 removes `classify` from the harvest node sequence).
- Produces: `state.unique_items` (unchanged).

**Why:** the harvest graph (Task 9) ends `load_sources → fetch_listings → extract_item_links → fetch_items → parse_extract → deduplicate → persist_notices` — no `classify` step. `state.relevant_items` is only ever set by `classify_with_keywords`/`classify_with_llm`. Left unfixed, harvest's `deduplicate` step would see an always-empty `relevant_items` and persist zero notices, every run.

- [ ] **Step 1: Write the failing test**

Read `tests/nodes/test_deduplicate.py` in full first. Update the two tests that construct state via `relevant_items=[...]`:

Current:
```python
def test_deduplicate_hash_only_uses_country_config():
    def h(s): return hashlib.sha256(s.encode()).hexdigest()

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_DEDUP,
        relevant_items=[
            {"id": "a", "title": "Tender A", "content_hash": h("unique_a")},
            {"id": "b", "title": "Tender B", "content_hash": h("unique_b")},
            {"id": "c", "title": "Tender A dup", "content_hash": h("unique_a")},
        ],
    )
    result = deduplicate_node(state)
    unique_ids = [i["id"] for i in result.unique_items]
    assert "a" in unique_ids
    assert "b" in unique_ids
    assert "c" not in unique_ids


def test_deduplicate_fails_hard_if_config_missing():
    state = TenderAIState(
        country_id=1,
        country_config={},
        relevant_items=[{"id": "a", "title": "T", "content_hash": "abc"}],
    )
    with pytest.raises(RuntimeError, match="Missing DB config"):
        deduplicate_node(state)
```

Replace with:
```python
def test_deduplicate_hash_only_uses_country_config():
    def h(s): return hashlib.sha256(s.encode()).hexdigest()

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_DEDUP,
        items_parsed=[
            {"id": "a", "title": "Tender A", "content_hash": h("unique_a")},
            {"id": "b", "title": "Tender B", "content_hash": h("unique_b")},
            {"id": "c", "title": "Tender A dup", "content_hash": h("unique_a")},
        ],
    )
    result = deduplicate_node(state)
    unique_ids = [i["id"] for i in result.unique_items]
    assert "a" in unique_ids
    assert "b" in unique_ids
    assert "c" not in unique_ids


def test_deduplicate_fails_hard_if_config_missing():
    state = TenderAIState(
        country_id=1,
        country_config={},
        items_parsed=[{"id": "a", "title": "T", "content_hash": "abc"}],
    )
    with pytest.raises(RuntimeError, match="Missing DB config"):
        deduplicate_node(state)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_deduplicate.py -v --no-cov`
Expected: FAIL — `deduplicate_node` still reads `state.relevant_items`, which is now empty (default `[]`), so `result.unique_items` is `[]` and the assertions fail.

- [ ] **Step 3: Fix `deduplicate_node`**

Three exact changes in `src/tenderai_bf/agents/nodes/deduplicate.py`:

1. The initial guard:
```python
        if not state.relevant_items:
            state.unique_items = []
            return state
```
becomes:
```python
        if not state.items_parsed:
            state.unique_items = []
            return state
```

2. The main loop:
```python
        for item in state.relevant_items:
```
becomes:
```python
        for item in state.items_parsed:
```

3. The final log line:
```python
        logger.info(
            "Deduplicate completed",
            method=method,
            relevant_items=len(state.relevant_items),
            unique_items=len(unique_items),
            duplicates_removed=len(similar_items),
            run_id=state.run_id,
        )
```
becomes:
```python
        logger.info(
            "Deduplicate completed",
            method=method,
            items_parsed=len(state.items_parsed),
            unique_items=len(unique_items),
            duplicates_removed=len(similar_items),
            run_id=state.run_id,
        )
```

Everything else in the function (the 5 dedup method branches, `content_hash`/`tender_object`/`reference` field reads on each item, `state.unique_items = unique_items`, `state.update_stats(...)`) is unchanged — only the input field name changes, not the dedup algorithm.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_deduplicate.py -v --no-cov`
Expected: PASS (full file — this file also has tests for `similarity_only`/`hash_similarity`/`llm_only`/`hybrid` methods; if any of those also construct state via `relevant_items=`, apply the same rename — check with `grep -n "relevant_items=" tests/nodes/test_deduplicate.py` and fix every hit, not just the two shown above).

- [ ] **Step 5: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline.

- [ ] **Step 6: Commit**

```bash
git add src/tenderai_bf/agents/nodes/deduplicate.py tests/nodes/test_deduplicate.py
git commit -m "fix(pipeline): deduplicate_node reads items_parsed, not relevant_items

The harvest graph (next task) no longer includes classify — relevant_items
is only ever set by classify_with_keywords/classify_with_llm, so
deduplicate_node reading it would always see an empty list once classify
moves to the delivery graph. Reads items_parsed instead; dedup algorithm
itself is unchanged."
```

---

## Task 8: New `persist_notices` harvest step

**Files:**
- Create: `src/tenderai_bf/agents/nodes/persist_notices.py`
- Test: `tests/nodes/test_persist_notices.py`

**Interfaces:**
- Consumes: `state.unique_items` (from `deduplicate_node`, Task 7's fix), `state.sources` (from `load_sources_node`, unchanged — list of dicts with `id`/`name`/`country_id`), `state.country_id`, `state.run_id`.
- Produces: `persist_notices_node(state) -> state` — inserts a `Notice` row per successfully-resolved item; adds `state.add_warning("persist_notices", ...)` per skipped item (unresolved source). Does not set `state.unique_items`/other fields — this is a terminal, DB-side-effecting step.

- [ ] **Step 1: Write the failing test**

Create `tests/nodes/test_persist_notices.py`:
```python
import hashlib
import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenderai_bf.agents.graph import TenderAIState
from tenderai_bf.agents.nodes.persist_notices import persist_notices_node
from tenderai_bf.db import Base
from tenderai_bf.models import Country, Notice, Run, Source


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    country = Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True)
    source_a = Source(id=10, name="DGCMEF Burkina Faso", base_url="https://dgcmef.gov.bf",
                       list_url="https://dgcmef.gov.bf/list", parser_type="html",
                       enabled=True, country_id=1)
    run = Run(id="run-1", status="running", triggered_by="test", country_id=1)
    session.add_all([country, source_a, run])
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.persist_notices.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_persist_notices_resolves_by_source_name(db_session):
    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[{"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1}],
        unique_items=[
            {
                "id": "item-1",
                "title": "Acquisition de serveurs",
                "url": "https://dgcmef.gov.bf/notice/1",
                "content_hash": _h("notice-1"),
                "source_name": "DGCMEF Burkina Faso",
                "entity": "Ministère X",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred

    notices = db_session.query(Notice).all()
    assert len(notices) == 1
    assert notices[0].source_id == 10
    assert notices[0].run_id == "run-1"
    assert notices[0].title == "Acquisition de serveurs"
    assert notices[0].is_relevant is False  # column default — harvest never sets this
    assert notices[0].relevance_score is None


def test_persist_notices_resolves_by_source_tag_substring(db_session):
    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[{"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1}],
        unique_items=[
            {
                "id": "item-2",
                "title": "Fourniture d'équipements réseau",
                "url": "https://dgcmef.gov.bf/notice/2",
                "content_hash": _h("notice-2"),
                # No source_name — only a generic pathway tag. Won't substring-match
                # "DGCMEF Burkina Faso", so this falls through to the
                # single-source-per-country fallback (only one Source for
                # country_id=1 in this fixture).
                "source": "html",
                "entity": "Ministère Y",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred
    notices = db_session.query(Notice).all()
    assert len(notices) == 1
    assert notices[0].source_id == 10


def test_persist_notices_skips_unresolvable_source_with_warning(db_session):
    # Add a second source so the single-source fallback no longer applies.
    from tenderai_bf.models import Source
    db_session.add(Source(id=11, name="UNGM", base_url="https://ungm.org",
                           list_url="https://ungm.org/list", parser_type="html",
                           enabled=True, country_id=1))
    db_session.commit()

    state = TenderAIState(
        run_id="run-1",
        country_id=1,
        sources=[
            {"id": 10, "name": "DGCMEF Burkina Faso", "country_id": 1},
            {"id": 11, "name": "UNGM", "country_id": 1},
        ],
        unique_items=[
            {
                "id": "item-3",
                "title": "Some tender",
                "url": "https://example.com/notice/3",
                "content_hash": _h("notice-3"),
                # No source_name, no matching source tag, and now two possible
                # sources — must be skipped with a warning, not guessed.
                "source": "unknown_pathway",
                "entity": "Entity Z",
                "is_duplicate": False,
            },
        ],
    )
    result = persist_notices_node(state)
    assert not result.error_occurred
    notices = db_session.query(Notice).all()
    assert len(notices) == 0
    assert len(result.warnings) == 1
    assert result.warnings[0]["step"] == "persist_notices"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_persist_notices.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'tenderai_bf.agents.nodes.persist_notices'`

- [ ] **Step 3: Implement `persist_notices_node`**

Create `src/tenderai_bf/agents/nodes/persist_notices.py`:
```python
"""Persist deduplicated harvest items as Notice rows.

Structural persistence only — is_relevant/relevance_score/classification_method
are never written here (harvest has no relevance information; classify_node in
the delivery graph is the sole place relevance is decided, per company).

Source attribution is best-effort: most item types today don't reliably carry
a field that matches a Source.id row (verified directly against the pipeline's
actual fetchers/parsers, not assumed) — see this plan's Global Constraints.
Items whose source can't be confidently resolved are skipped with a non-fatal
warning rather than persisted with a guessed source_id.
"""

import time
import uuid

from ...db import get_db_context
from ...logging import get_logger
from ...models import Notice
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def _resolve_source_id(item: dict, sources: list[dict]) -> int | None:
    """Best-effort source_id resolution. See module docstring for the fallback order."""
    source_name = (item.get("source_name") or "").strip().lower()
    if source_name:
        for s in sources:
            if s["name"].strip().lower() == source_name:
                return s["id"]

    source_tag = (item.get("source") or "").strip().lower()
    if source_tag:
        matches = [s for s in sources if source_tag in s["name"].strip().lower()]
        if len(matches) == 1:
            return matches[0]["id"]

    if len(sources) == 1:
        return sources[0]["id"]

    return None


def persist_notices_node(state) -> dict:
    """Insert a Notice row for each deduplicated harvest item."""

    clear_node_output("persist_notices")

    if state.error_occurred:
        return state

    logger.info("Starting persist_notices step", run_id=state.run_id)
    start_time = time.time()

    items = getattr(state, "unique_items", None) or []
    sources = getattr(state, "sources", None) or []

    persisted_count = 0
    skipped_count = 0

    try:
        with get_db_context() as db:
            for item in items:
                source_id = _resolve_source_id(item, sources)
                if source_id is None:
                    skipped_count += 1
                    state.add_warning(
                        "persist_notices",
                        "Could not resolve source for item — skipped",
                        item_id=item.get("id"),
                        item_source=item.get("source") or item.get("source_name"),
                    )
                    continue

                notice = Notice(
                    id=item.get("id") or str(uuid.uuid4()),
                    source_id=source_id,
                    run_id=state.run_id,
                    title=item.get("title") or item.get("tender_object") or "",
                    ref_no=item.get("ref_no") or item.get("reference"),
                    entity=item.get("entity"),
                    category=item.get("category"),
                    published_at=item.get("published_at"),
                    deadline_at=item.get("deadline_at") or item.get("deadline"),
                    location=item.get("location"),
                    budget_xof=item.get("budget_xof"),
                    currency=item.get("currency"),
                    description=item.get("description"),
                    content_hash=item.get("content_hash") or "",
                    is_duplicate=bool(item.get("is_duplicate", False)),
                    duplicate_of_id=item.get("duplicate_of_id"),
                    url=item.get("url") or "",
                )
                db.add(notice)
                persisted_count += 1

            db.commit()

        state.update_stats(
            notices_persisted=persisted_count,
            persist_time_seconds=time.time() - start_time,
        )

        log_node_output(
            "persist_notices",
            {"persisted": persisted_count, "skipped": skipped_count},
            run_id=state.run_id,
        )

        logger.info(
            "Persist notices completed",
            persisted=persisted_count,
            skipped=skipped_count,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Persist notices step failed", error=str(e), run_id=state.run_id, exc_info=True
        )
        state.add_error("persist_notices", str(e))
        return state
```

Note: `content_hash`/`url` default to `""` rather than `None` if absent from the item dict, since `Notice.content_hash`/`Notice.url` are `nullable=False` — a truly missing hash or URL is a data-quality problem upstream, not something this step should crash on (matches this codebase's existing best-effort-persistence philosophy), but it also shouldn't silently insert `NULL` into a non-null column. `title` similarly falls back to `""` (also `nullable=False`).

Check `TenderAIState.update_stats()` (in `agents/graph.py`) and `RunStatistics` (in `schemas.py`) — `update_stats` only sets attributes that already exist on `self.stats` (`if hasattr(self.stats, key)`), so if `RunStatistics` doesn't have `notices_persisted`/`persist_time_seconds` fields, this call is a silent no-op (matches the codebase's existing tolerant pattern — check `src/tenderai_bf/schemas.py`'s `RunStatistics` class; do NOT add new fields to it as part of this task, that's optional polish outside this plan's scope).

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_persist_notices.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline.

- [ ] **Step 6: Commit**

```bash
git add src/tenderai_bf/agents/nodes/persist_notices.py tests/nodes/test_persist_notices.py
git commit -m "feat(pipeline): add persist_notices harvest step

New node, structural fields only (no relevance columns written). Source
resolution is a documented best-effort fallback chain — exact source_name
match, then substring source-tag match, then single-source-per-country
default, then skip-with-warning. Full source-attribution correctness across
every upstream fetcher is out of scope for this plan (see Global Constraints)."
```

---

## Task 9: `agents/graph.py` — `TenderAIGraph` becomes harvest-only

**Files:**
- Modify: `src/tenderai_bf/agents/graph.py`
- Test: `tests/test_pipeline_country.py`

**Interfaces:**
- Consumes: `persist_notices_node` (Task 8).
- Produces: `TenderAIGraph`/`create_pipeline_graph()`/`get_pipeline()` — same names, now harvest-only behavior. `TenderAIGraph.run(country_id, ...)` no longer accepts/uses `send_email`/`test_mode` meaningfully (harvest has no email step) — kept as accepted-but-ignored parameters for now rather than removed, since 3 external callers (`cli.py`, `scheduler/schedule.py`, `api/routers/runs.py`) still pass them; Tasks 14-16 update those call sites, this task only changes what `TenderAIGraph` itself does with them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline_country.py` (read the file first to match its existing mocking style — it already patches `tenderai_bf.agents.graph.get_db_context`/`CountryStore`):
```python
def test_harvest_graph_has_no_classify_or_email_nodes():
    from tenderai_bf.agents.graph import TenderAIGraph

    graph = TenderAIGraph()
    node_names = set(graph.graph.nodes.keys())
    assert "persist_notices" in node_names
    assert "classify" not in node_names
    assert "summarize" not in node_names
    assert "compose_report" not in node_names
    assert "email_report" not in node_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_pipeline_country.py -v --no-cov -k harvest_graph_has_no`
Expected: FAIL — `classify`/`summarize`/`compose_report`/`email_report` are still registered, `persist_notices` doesn't exist yet in the graph.

- [ ] **Step 3: Update node imports**

Current imports (`agents/graph.py`, top of file):
```python
from .nodes.classify import classify_node
from .nodes.compose_report import compose_report_node
from .nodes.deduplicate import deduplicate_node
from .nodes.email_report import email_report_node
from .nodes.extract_item_links import extract_item_links_node
from .nodes.fetch_items import fetch_items_node
from .nodes.fetch_listings import fetch_listings_node

# Import node functions
from .nodes.load_sources import load_sources_node
from .nodes.parse_extract import parse_extract_node
from .nodes.summarize import summarize_node
```

Replace with:
```python
from .nodes.deduplicate import deduplicate_node
from .nodes.extract_item_links import extract_item_links_node
from .nodes.fetch_items import fetch_items_node
from .nodes.fetch_listings import fetch_listings_node

# Import node functions
from .nodes.load_sources import load_sources_node
from .nodes.parse_extract import parse_extract_node
from .nodes.persist_notices import persist_notices_node
```

- [ ] **Step 4: Update `_build_graph()`**

Current:
```python
        # Create state graph
        workflow = StateGraph(TenderAIState)

        # Add nodes
        workflow.add_node("load_sources", load_sources_node)
        workflow.add_node("fetch_listings", fetch_listings_node)
        workflow.add_node("extract_item_links", extract_item_links_node)
        workflow.add_node("fetch_items", fetch_items_node)
        workflow.add_node("parse_extract", parse_extract_node)
        workflow.add_node("classify", classify_node)
        workflow.add_node("deduplicate", deduplicate_node)
        workflow.add_node("summarize", summarize_node)
        workflow.add_node("compose_report", compose_report_node)
        workflow.add_node("email_report", email_report_node)
        workflow.add_node("error_handler", error_handler)

        # Set entry point
        workflow.set_entry_point("load_sources")

        # Sequence of steps that must short-circuit on error.
        sequential_edges = [
            ("load_sources", "fetch_listings"),
            ("fetch_listings", "extract_item_links"),
            ("extract_item_links", "fetch_items"),
            ("fetch_items", "parse_extract"),
            ("parse_extract", "classify"),
            ("classify", "deduplicate"),
            ("deduplicate", "summarize"),
            ("summarize", "compose_report"),
            ("compose_report", "email_report"),
        ]
        for src, dst in sequential_edges:
            workflow.add_conditional_edges(
                src,
                _route_after_step,
                {"continue": dst, "error_handler": "error_handler"},
            )

        # email_report is the last data-producing node. By this point we want
        # the run to terminate normally even if email delivery emitted a
        # non-fatal warning (see email_report_node), so we only divert to the
        # error_handler when an actual fatal error was recorded.
        workflow.add_conditional_edges(
            "email_report",
            _route_after_step,
            {"continue": END, "error_handler": "error_handler"},
        )

        workflow.add_edge("error_handler", END)

        return workflow
```

Replace with:
```python
        # Create state graph
        workflow = StateGraph(TenderAIState)

        # Add nodes
        workflow.add_node("load_sources", load_sources_node)
        workflow.add_node("fetch_listings", fetch_listings_node)
        workflow.add_node("extract_item_links", extract_item_links_node)
        workflow.add_node("fetch_items", fetch_items_node)
        workflow.add_node("parse_extract", parse_extract_node)
        workflow.add_node("deduplicate", deduplicate_node)
        workflow.add_node("persist_notices", persist_notices_node)
        workflow.add_node("error_handler", error_handler)

        # Set entry point
        workflow.set_entry_point("load_sources")

        # Sequence of steps that must short-circuit on error.
        sequential_edges = [
            ("load_sources", "fetch_listings"),
            ("fetch_listings", "extract_item_links"),
            ("extract_item_links", "fetch_items"),
            ("fetch_items", "parse_extract"),
            ("parse_extract", "deduplicate"),
        ]
        for src, dst in sequential_edges:
            workflow.add_conditional_edges(
                src,
                _route_after_step,
                {"continue": dst, "error_handler": "error_handler"},
            )

        # persist_notices is the last data-producing node.
        workflow.add_conditional_edges(
            "deduplicate",
            _route_after_step,
            {"continue": "persist_notices", "error_handler": "error_handler"},
        )
        workflow.add_conditional_edges(
            "persist_notices",
            _route_after_step,
            {"continue": END, "error_handler": "error_handler"},
        )

        workflow.add_edge("error_handler", END)

        return workflow
```

- [ ] **Step 5: Set `run_type="harvest"` explicitly on the `Run` row**

Current (`agents/graph.py`, inside `run()`):
```python
                run = Run(
                    id=run_id,
                    status="running",
                    started_at=state.started_at,
                    triggered_by=triggered_by,
                    triggered_by_user=triggered_by_user,
                    country_id=country_id,
                )
```

Replace with:
```python
                run = Run(
                    id=run_id,
                    status="running",
                    started_at=state.started_at,
                    triggered_by=triggered_by,
                    triggered_by_user=triggered_by_user,
                    country_id=country_id,
                    run_type="harvest",
                )
```

(`run_type` already defaults to `"harvest"` at the column level, so this doesn't change current behavior — but is explicit rather than relying on an implicit default, matching how the new delivery graph, Task 10, must set `run_type="delivery"` explicitly since there the default would be wrong.)

- [ ] **Step 6: Run test to verify it passes**

Run: `poetry run pytest tests/test_pipeline_country.py -v --no-cov`
Expected: PASS. No other test in this file needs changes: `test_run_sets_country_id_on_state` only asserts on `state.country_id`/`country_name`/`country_config` via a mocked `graph.app.invoke`, not on node presence or output fields — unaffected by the node-sequence change. (The 2 classify-scoping tests in this same file were already updated in Task 6.)

- [ ] **Step 7: Verify `test_integration.py`/`test_smoke.py` need no changes (already confirmed, not speculative)**

Both `tests/test_integration.py::TestPipelineIntegration::test_pipeline_state_creation`/`test_pipeline_graph_creation` and `tests/test_smoke.py::test_pipeline_graph` were read in full while writing this task. Neither asserts on specific node names, `result.report_url`, or `result.email_status` — they construct `TenderAIState` with several field names that don't even exist on the real class (`raw_listings`, `item_links`, `classified_items`, etc. — Pydantic v1 silently ignores unrecognized kwargs, so these were already vestigial before this plan) and only assert on `state.run_id`/`state.sources`/generic graph non-nullness/`len(graph.graph.nodes) > 0`. Both keep passing unchanged after this task's node-sequence edit. No action needed in this step beyond the full-suite run below.

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -20`
Expected: no new failures beyond the pre-task baseline (the pre-existing Docker/Postgres/MinIO-dependent failures in `test_integration.py` are unrelated to this change).

- [ ] **Step 8: Commit**

```bash
git add src/tenderai_bf/agents/graph.py tests/test_pipeline_country.py
git commit -m "feat(pipeline): TenderAIGraph becomes harvest-only

Node sequence now ends load_sources -> ... -> deduplicate -> persist_notices.
classify/summarize/compose_report/email_report move to the new delivery
graph (next task). Run rows created here are explicitly run_type='harvest'."
```

---

## Task 10: New `agents/delivery_graph.py`

**Files:**
- Create: `src/tenderai_bf/agents/delivery_graph.py`
- Create: `src/tenderai_bf/agents/nodes/select_new_notices.py`
- Create: `src/tenderai_bf/agents/nodes/mark_delivered.py`
- Test: `tests/nodes/test_select_new_notices.py`, `tests/nodes/test_mark_delivered.py`, `tests/test_delivery_graph.py`

**Interfaces:**
- Consumes: `TenderAIState`/`_route_after_step`/`error_handler`/`_AppWrapper`/`cfg` (from `agents/graph.py`, unchanged import path per this plan's Global Constraints), `CompanyStore.get_all_with_fallback` (existing, from `src/tenderai_bf/company_store.py`), `classify_node`/`summarize_node`/`compose_report_node`/`email_report_node` (existing node functions — `classify_node` gains `CompanyNoticeStatus` writes in Task 11, after this task).
- Produces: `DeliveryGraph` class, `create_delivery_graph() -> DeliveryGraph`, `get_delivery_pipeline() -> DeliveryGraph` (thread-safe singleton, mirrors `get_pipeline()`). `DeliveryGraph.run(company_id: int, country_id: int, triggered_by: str = "scheduler", triggered_by_user: str | None = None, test_mode: bool = False) -> TenderAIState`.

- [ ] **Step 1: Write the failing test for `select_new_notices_node`**

Create `tests/nodes/test_select_new_notices.py`:
```python
import hashlib
import os
import uuid

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenderai_bf.agents.graph import TenderAIState
from tenderai_bf.agents.nodes.select_new_notices import select_new_notices_node
from tenderai_bf.db import Base
from tenderai_bf.models import Company, CompanyNoticeStatus, Country, Notice, Run, Source


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)

    session.add_all([
        Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True),
        Source(id=10, name="DGCMEF Burkina Faso", base_url="https://x", list_url="https://x/l",
               parser_type="html", enabled=True, country_id=1),
        Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True),
        Run(id="run-1", status="completed", triggered_by="test", country_id=1, run_type="harvest"),
    ])
    session.commit()

    notice_seen = Notice(
        id="notice-seen", source_id=10, run_id="run-1", title="Already classified",
        content_hash=hashlib.sha256(b"seen").hexdigest(), url="https://x/1",
    )
    notice_new = Notice(
        id="notice-new", source_id=10, run_id="run-1", title="Not yet classified",
        content_hash=hashlib.sha256(b"new").hexdigest(), url="https://x/2",
    )
    session.add_all([notice_seen, notice_new])
    session.add(CompanyNoticeStatus(
        id=str(uuid.uuid4()), company_id=1, notice_id="notice-seen", is_relevant=True,
    ))
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.select_new_notices.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


def test_select_new_notices_excludes_already_classified(db_session):
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    assert not result.error_occurred
    ids = [i["id"] for i in result.items_parsed]
    assert "notice-new" in ids
    assert "notice-seen" not in ids


def test_select_new_notices_returns_classify_compatible_dicts(db_session):
    state = TenderAIState(run_id="run-2", country_id=1, company_id=1)
    result = select_new_notices_node(state)
    item = next(i for i in result.items_parsed if i["id"] == "notice-new")
    assert item["title"] == "Not yet classified"
    assert "entity" in item
    assert "description" in item
    assert "location" in item
    assert "reference" in item
    assert "deadline" in item
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_select_new_notices.py -v --no-cov`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement `select_new_notices_node`**

Create `src/tenderai_bf/agents/nodes/select_new_notices.py`:
```python
"""Select Notice rows a company hasn't classified yet, for one country.

A CompanyNoticeStatus row's absence is the delivery cursor — a Notice with
no row for this (company_id, notice_id) pair hasn't been classified/seen by
this company yet.
"""

import time

from sqlalchemy import and_, not_, select

from ...db import get_db_context
from ...logging import get_logger
from ...models import CompanyNoticeStatus, Notice, Source
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def _notice_to_classify_dict(notice: Notice) -> dict:
    """Shape a Notice row into the dict format classify_node already consumes."""
    return {
        "id": notice.id,
        "title": notice.title,
        "tender_object": notice.title,
        "ref_no": notice.ref_no,
        "reference": notice.ref_no,
        "entity": notice.entity,
        "category": notice.category,
        "published_at": notice.published_at.isoformat() if notice.published_at else None,
        "deadline_at": notice.deadline_at.isoformat() if notice.deadline_at else None,
        "deadline": notice.deadline_at.isoformat() if notice.deadline_at else None,
        "location": notice.location,
        "budget_xof": notice.budget_xof,
        "currency": notice.currency,
        "description": notice.description,
        "url": notice.url,
        "content_hash": notice.content_hash,
        "keywords": [],
    }


def select_new_notices_node(state) -> dict:
    """Load unclassified Notice rows for this (company, country) pair."""

    clear_node_output("select_new_notices")

    if state.error_occurred:
        return state

    logger.info(
        "Starting select_new_notices step",
        company_id=state.company_id,
        country_id=state.country_id,
        run_id=state.run_id,
    )
    start_time = time.time()

    try:
        with get_db_context() as db:
            already_classified = select(CompanyNoticeStatus.notice_id).where(
                CompanyNoticeStatus.company_id == state.company_id
            )
            notices = (
                db.query(Notice)
                .join(Source, Notice.source_id == Source.id)
                .filter(
                    and_(
                        Source.country_id == state.country_id,
                        not_(Notice.id.in_(already_classified)),
                    )
                )
                .all()
            )
            items = [_notice_to_classify_dict(n) for n in notices]

        state.items_parsed = items
        state.update_stats(items_parsed=len(items))

        log_node_output("select_new_notices", items, run_id=state.run_id)

        logger.info(
            "Select new notices completed",
            count=len(items),
            company_id=state.company_id,
            country_id=state.country_id,
            duration_seconds=time.time() - start_time,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Select new notices step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True,
        )
        state.add_error("select_new_notices", str(e))
        return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_select_new_notices.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Write the failing test for `mark_delivered_node`**

Create `tests/nodes/test_mark_delivered.py`:
```python
import os
import uuid

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenderai_bf.agents.graph import TenderAIState
from tenderai_bf.agents.nodes.mark_delivered import mark_delivered_node
from tenderai_bf.db import Base
from tenderai_bf.models import Company, CompanyNoticeStatus


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True))
    session.add(CompanyNoticeStatus(
        id="cns-1", company_id=1, notice_id="notice-a", is_relevant=True, delivered_at=None,
    ))
    session.add(CompanyNoticeStatus(
        id="cns-2", company_id=1, notice_id="notice-b", is_relevant=False, delivered_at=None,
    ))
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.mark_delivered.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


def test_mark_delivered_sets_delivered_at_for_reported_items(db_session):
    state = TenderAIState(
        run_id="run-1",
        company_id=1,
        unique_items=[{"id": "notice-a", "title": "A"}],
    )
    result = mark_delivered_node(state)
    assert not result.error_occurred

    row_a = db_session.query(CompanyNoticeStatus).filter_by(notice_id="notice-a").first()
    row_b = db_session.query(CompanyNoticeStatus).filter_by(notice_id="notice-b").first()
    assert row_a.delivered_at is not None
    assert row_b.delivered_at is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_mark_delivered.py -v --no-cov`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 7: Implement `mark_delivered_node`**

Create `src/tenderai_bf/agents/nodes/mark_delivered.py`:
```python
"""Mark CompanyNoticeStatus rows as delivered for whichever notices made it
into the sent report."""

import time
from datetime import datetime

from ...db import get_db_context
from ...logging import get_logger
from ...models import CompanyNoticeStatus
from ...utils.node_logger import clear_node_output, log_node_output

logger = get_logger(__name__)


def mark_delivered_node(state) -> dict:
    """Set delivered_at on the CompanyNoticeStatus rows for reported items."""

    clear_node_output("mark_delivered")

    if state.error_occurred:
        return state

    logger.info("Starting mark_delivered step", run_id=state.run_id)
    start_time = time.time()

    reported_items = getattr(state, "unique_items", None) or []
    notice_ids = [item["id"] for item in reported_items if item.get("id")]

    if not notice_ids:
        logger.info("No delivered items to mark", run_id=state.run_id)
        return state

    try:
        with get_db_context() as db:
            rows = (
                db.query(CompanyNoticeStatus)
                .filter(
                    CompanyNoticeStatus.company_id == state.company_id,
                    CompanyNoticeStatus.notice_id.in_(notice_ids),
                )
                .all()
            )
            now = datetime.utcnow()
            for row in rows:
                row.delivered_at = now
            db.commit()

        log_node_output(
            "mark_delivered", {"marked_count": len(rows)}, run_id=state.run_id
        )

        logger.info(
            "Mark delivered completed",
            marked_count=len(rows),
            duration_seconds=time.time() - start_time,
            run_id=state.run_id,
        )

        return state

    except Exception as e:
        logger.error(
            "Mark delivered step failed", error=str(e), run_id=state.run_id, exc_info=True
        )
        state.add_error("mark_delivered", str(e))
        return state
```

- [ ] **Step 8: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_mark_delivered.py -v --no-cov`
Expected: PASS

- [ ] **Step 9: Write the failing test for `DeliveryGraph`**

Create `tests/test_delivery_graph.py`:
```python
import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


def test_delivery_graph_node_sequence():
    from tenderai_bf.agents.delivery_graph import DeliveryGraph

    graph = DeliveryGraph()
    node_names = set(graph.graph.nodes.keys())
    assert node_names == {
        "select_new_notices", "classify", "summarize", "compose_report",
        "email_report", "mark_delivered", "error_handler",
    }
```

- [ ] **Step 10: Run test to verify it fails**

Run: `poetry run pytest tests/test_delivery_graph.py -v --no-cov`
Expected: FAIL — module doesn't exist.

- [ ] **Step 11: Implement `agents/delivery_graph.py`**

Create `src/tenderai_bf/agents/delivery_graph.py`:
```python
"""LangGraph pipeline for delivering classified notices to one company.

Mirrors agents/graph.py's TenderAIGraph structure (_AppWrapper,
_route_after_step, error_handler — all imported, not duplicated) but for
the delivery side: select_new_notices -> classify -> summarize ->
compose_report -> email_report -> mark_delivered.
"""

import threading
import time
from datetime import datetime

from langgraph.graph import END, StateGraph

from ..company_store import CompanyStore
from ..country_store import CountryStore
from ..db import get_db_context
from ..logging import get_logger, log_run_complete, log_run_error, log_run_start
from ..models import Company, Country as CountryModel, Run
from .graph import TenderAIGraph, TenderAIState, _AppWrapper, _route_after_step, error_handler
from .nodes.classify import classify_node
from .nodes.compose_report import compose_report_node
from .nodes.email_report import email_report_node
from .nodes.mark_delivered import mark_delivered_node
from .nodes.select_new_notices import select_new_notices_node
from .nodes.summarize import summarize_node

logger = get_logger(__name__)


class DeliveryGraph:
    """LangGraph pipeline for delivering one company's classified notices."""

    def __init__(self):
        self.graph = self._build_graph()
        self.app = _AppWrapper(self.graph.compile())
        logger.info("Delivery pipeline graph initialized")

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(TenderAIState)

        workflow.add_node("select_new_notices", select_new_notices_node)
        workflow.add_node("classify", classify_node)
        workflow.add_node("summarize", summarize_node)
        workflow.add_node("compose_report", compose_report_node)
        workflow.add_node("email_report", email_report_node)
        workflow.add_node("mark_delivered", mark_delivered_node)
        workflow.add_node("error_handler", error_handler)

        workflow.set_entry_point("select_new_notices")

        sequential_edges = [
            ("select_new_notices", "classify"),
            ("classify", "summarize"),
            ("summarize", "compose_report"),
            ("compose_report", "email_report"),
        ]
        for src, dst in sequential_edges:
            workflow.add_conditional_edges(
                src,
                _route_after_step,
                {"continue": dst, "error_handler": "error_handler"},
            )

        # mark_delivered runs even after a non-fatal email warning, same
        # rationale as TenderAIGraph's email_report -> END edge.
        workflow.add_conditional_edges(
            "email_report",
            _route_after_step,
            {"continue": "mark_delivered", "error_handler": "error_handler"},
        )
        workflow.add_conditional_edges(
            "mark_delivered",
            _route_after_step,
            {"continue": END, "error_handler": "error_handler"},
        )

        workflow.add_edge("error_handler", END)

        return workflow

    def run(
        self,
        company_id: int,
        country_id: int,
        triggered_by: str = "scheduler",
        triggered_by_user: str | None = None,
        test_mode: bool = False,
    ) -> TenderAIState:
        """Execute the delivery pipeline for one (company, country) pair."""

        state = TenderAIState()
        run_id = state.run_id

        # Load country AND company context — classify needs country_config
        # (llm.provider) and company_config (classification), both.
        try:
            with get_db_context() as _db:
                _country = (
                    _db.query(CountryModel)
                    .filter(CountryModel.id == country_id)
                    .first()
                )
                if not _country:
                    state.add_error("delivery", f"Country {country_id} not found")
                    state.error_occurred = True
                    return state
                _company = _db.query(Company).filter(Company.id == company_id).first()
                if not _company:
                    state.add_error("delivery", f"Company {company_id} not found")
                    state.error_occurred = True
                    return state

                state.country_id = country_id
                state.country_name = _country.name
                state.country_locale = _country.locale
                state.country_config = CountryStore.get_all_with_fallback(_db, country_id)

                state.company_id = company_id
                state.company_config = CompanyStore.get_all_with_fallback(_db, company_id)
        except Exception as _e:
            state.add_error("delivery", f"Failed to load country/company config: {_e}")
            state.error_occurred = True
            return state

        log_run_start(
            run_id,
            triggered_by=triggered_by,
            triggered_by_user=triggered_by_user,
            sources_count=0,
        )

        state.test_mode = test_mode

        try:
            with get_db_context() as session:
                run = Run(
                    id=run_id,
                    status="running",
                    started_at=state.started_at,
                    triggered_by=triggered_by,
                    triggered_by_user=triggered_by_user,
                    country_id=country_id,
                    run_type="delivery",
                    company_id=company_id,
                )
                session.add(run)
                session.commit()
        except Exception as e:
            logger.error("Failed to create run record", error=str(e), run_id=run_id)

        try:
            start_time = time.time()
            raw_final = self.app.invoke(state)
            duration = time.time() - start_time

            final_state = TenderAIGraph._coerce_to_state(raw_final)
            final_state.stats.total_time_seconds = duration

            if final_state.error_occurred:
                run_status = "failed"
            elif final_state.warnings:
                run_status = "completed_with_warnings"
            else:
                run_status = "completed"

            try:
                with get_db_context() as session:
                    run = session.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.status = run_status
                        run.finished_at = datetime.utcnow()
                        run.counts_json = final_state.stats.dict()
                        run.report_url = final_state.report_url
                        if final_state.errors:
                            run.error_message = final_state.errors[-1]["error"]
                        elif final_state.warnings:
                            run.error_message = final_state.warnings[-1]["warning"]
                        session.commit()
            except Exception as db_error:
                logger.error(
                    "Failed to update run record after delivery completion",
                    error=str(db_error),
                    run_id=run_id,
                )

            if not final_state.error_occurred:
                log_run_complete(
                    run_id,
                    duration,
                    final_state.stats.dict(),
                    status=run_status,
                    warnings_count=len(final_state.warnings),
                )

            return final_state

        except Exception as e:
            logger.error(
                "Delivery execution failed", error=str(e), run_id=run_id, exc_info=True
            )

            try:
                with get_db_context() as session:
                    run = session.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.status = "failed"
                        run.finished_at = datetime.utcnow()
                        run.error_message = str(e)
                        session.commit()
            except Exception as db_error:
                logger.error("Failed to update failed run record", error=str(db_error))

            log_run_error(run_id, e)

            state.add_error("delivery", str(e))
            state.error_occurred = True
            return state


def create_delivery_graph() -> DeliveryGraph:
    """Create and return a new delivery graph instance."""
    return DeliveryGraph()


_delivery_pipeline: DeliveryGraph | None = None
_delivery_pipeline_lock = threading.Lock()


def get_delivery_pipeline() -> DeliveryGraph:
    """Get or create the global delivery pipeline instance (thread-safe)."""
    global _delivery_pipeline

    if _delivery_pipeline is None:
        with _delivery_pipeline_lock:
            if _delivery_pipeline is None:
                _delivery_pipeline = create_delivery_graph()

    return _delivery_pipeline
```

- [ ] **Step 12: Run test to verify it passes**

Run: `poetry run pytest tests/test_delivery_graph.py -v --no-cov`
Expected: PASS

- [ ] **Step 13: Export from `agents/__init__.py`**

Current:
```python
from .graph import TenderAIGraph, create_pipeline_graph, get_pipeline

__all__ = ["TenderAIGraph", "create_pipeline_graph", "get_pipeline"]
```

Replace with:
```python
from .delivery_graph import DeliveryGraph, create_delivery_graph, get_delivery_pipeline
from .graph import TenderAIGraph, create_pipeline_graph, get_pipeline

__all__ = [
    "TenderAIGraph",
    "create_pipeline_graph",
    "get_pipeline",
    "DeliveryGraph",
    "create_delivery_graph",
    "get_delivery_pipeline",
]
```

- [ ] **Step 14: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -20`
Expected: no new failures beyond baseline. `classify_node` in delivery still only sets `state.relevant_items` at this point (Task 11 adds `CompanyNoticeStatus` writes and — critically — the `state.unique_items` assignment `summarize`/`compose_report` need); `DeliveryGraph.run()` invoked end-to-end will error at `summarize`/`compose_report` today since `state.unique_items` stays unset until Task 11. This is expected — Task 10 establishes the graph shape and its two new nodes in isolation; Task 11 is what makes a full `DeliveryGraph.run()` actually produce a report.

- [ ] **Step 15: Commit**

```bash
git add src/tenderai_bf/agents/delivery_graph.py src/tenderai_bf/agents/nodes/select_new_notices.py src/tenderai_bf/agents/nodes/mark_delivered.py src/tenderai_bf/agents/__init__.py tests/nodes/test_select_new_notices.py tests/nodes/test_mark_delivered.py tests/test_delivery_graph.py
git commit -m "feat(pipeline): add DeliveryGraph, select_new_notices, mark_delivered

New agents/delivery_graph.py mirrors TenderAIGraph's _AppWrapper/
_route_after_step/error_handler pattern (imported from agents/graph.py,
not duplicated). Loads both country_config and company_config before
invoking the graph. classify/summarize/compose_report/email_report are
reused node functions, not copies."
```

---

## Task 11: `classify_node` writes `CompanyNoticeStatus`, sets `state.unique_items`

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/classify.py`
- Test: `tests/nodes/test_classify.py`

**Interfaces:**
- Consumes: `CompanyNoticeStatus` model, `TenderAIState.company_id`.
- Produces: after `classify_with_keywords`/`classify_with_llm` compute relevance, each classified item gets an upserted `CompanyNoticeStatus` row (`delivered_at=NULL`); `state.unique_items` is set to the same list as `state.relevant_items` (Critical Finding #2's fix — nothing else populates `unique_items` in the delivery graph, and `summarize_node`/`compose_report_node` both read it unconditionally).

**Why `state.unique_items = relevant_items` here, not a dedicated node:** delivery has no dedup step (harvest already deduped before persisting) — `classify` is delivery's last item-shaping step before `summarize`, so it's the natural place to also satisfy `summarize`/`compose_report`'s existing `state.unique_items` dependency without touching either of those two node implementations.

- [ ] **Step 1: Write the failing test**

Add to `tests/nodes/test_classify.py` (after the tests from Task 6):
```python
def test_classify_sets_unique_items_for_delivery_report():
    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {"id": "t1", "title": "Acquisition de serveurs et réseau",
             "description": "Fourniture de serveurs", "category": "IT",
             "entity": "Ministère", "keywords": []},
        ],
    )
    result = classify_with_keywords(state)
    assert result.unique_items == result.relevant_items


def test_classify_writes_company_notice_status_for_every_item(monkeypatch, tmp_path):
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from tenderai_bf.db import Base
    from tenderai_bf.models import Company, CompanyNoticeStatus, Country, Notice, Run, Source

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([
        Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True),
        Source(id=10, name="DGCMEF", base_url="https://x", list_url="https://x/l",
               parser_type="html", enabled=True, country_id=1),
        Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True),
        Run(id="run-1", status="running", triggered_by="test", country_id=1),
    ])
    session.add_all([
        Notice(id="t1", source_id=10, run_id="run-1", title="Acquisition de serveurs",
               content_hash="h1", url="https://x/1"),
        Notice(id="t2", source_id=10, run_id="run-1", title="Construction de routes",
               content_hash="h2", url="https://x/2"),
    ])
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.classify.get_db_context", _fake_get_db_context
    )

    state = TenderAIState(
        country_id=1,
        country_config=COUNTRY_CONFIG_CLASSIFY,
        company_id=1,
        company_config=COMPANY_CONFIG_CLASSIFY,
        items_parsed=[
            {"id": "t1", "title": "Acquisition de serveurs et réseau",
             "description": "Fourniture de serveurs", "category": "IT",
             "entity": "Ministère", "keywords": []},
            {"id": "t2", "title": "Construction de routes rurales",
             "description": "Travaux BTP", "category": "BTP",
             "entity": "Mairie", "keywords": []},
        ],
    )
    classify_with_keywords(state)

    rows = session.query(CompanyNoticeStatus).filter_by(company_id=1).all()
    assert len(rows) == 2  # every classified item, relevant or not
    by_notice = {r.notice_id: r for r in rows}
    assert by_notice["t1"].is_relevant is True
    assert by_notice["t2"].is_relevant is False
    assert by_notice["t1"].delivered_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_classify.py -v --no-cov -k "unique_items_for_delivery or writes_company_notice_status"`
Expected: FAIL — `state.unique_items` isn't set, no `CompanyNoticeStatus` rows exist.

- [ ] **Step 3: Add the `CompanyNoticeStatus` upsert helper**

Add to `src/tenderai_bf/agents/nodes/classify.py`, near the top (after imports, before `_normalize_apostrophes`/other helpers — check current file structure with `grep -n "^def \|^from\|^import" src/tenderai_bf/agents/nodes/classify.py` first):
```python
def _upsert_company_notice_status(
    db, company_id: int, item: dict
) -> None:
    """Record this item's classification result for this company.

    Every classified item gets a row (relevant or not) — a row's absence is
    what select_new_notices treats as "not yet classified", so an item with
    no row would be reclassified on every future delivery run.
    """
    existing = (
        db.query(CompanyNoticeStatus)
        .filter(
            CompanyNoticeStatus.company_id == company_id,
            CompanyNoticeStatus.notice_id == item["id"],
        )
        .first()
    )
    if existing:
        existing.is_relevant = bool(item.get("is_relevant", False))
        existing.relevance_score = item.get("relevance_score")
        existing.classification_method = item.get("classification_method")
    else:
        db.add(
            CompanyNoticeStatus(
                id=str(uuid.uuid4()),
                company_id=company_id,
                notice_id=item["id"],
                is_relevant=bool(item.get("is_relevant", False)),
                relevance_score=item.get("relevance_score"),
                classification_method=item.get("classification_method"),
            )
        )
```

Add the needed imports at the top of the file (check what's already imported first — `uuid` may already be imported):
```python
import uuid

from ...db import get_db_context
from ...models import CompanyNoticeStatus
```

- [ ] **Step 4: Call the upsert helper and set `unique_items` at the end of `classify_with_keywords`**

Find where `classify_with_keywords` currently ends (after building `relevant_items`, before `return state` — check exact current lines with `grep -n "state.relevant_items = relevant_items" src/tenderai_bf/agents/nodes/classify.py`, this appears once per function). Current end-of-function shape (approximately):
```python
    state.relevant_items = relevant_items
    state.update_stats(...)
    ...
    return state
```

Insert the upsert loop and `unique_items` assignment right after `state.relevant_items = relevant_items` is set, and before whatever logging/stats calls follow it:
```python
    state.relevant_items = relevant_items
    state.unique_items = relevant_items

    with get_db_context() as _db:
        for item in items_processed:
            _upsert_company_notice_status(_db, state.company_id, item)
        _db.commit()
```

Where `items_processed` is every item that went through classification in this function (relevant AND not-relevant — i.e., `state.items_parsed`, since every item in the input list gets a `CompanyNoticeStatus` row regardless of outcome; items short-circuited by the disqualification filters — geographic/attribution/supplier-registration/expired — also count as "classified", just as not-relevant, so they need rows too). Read the function's actual variable names around its loop (`for item in state.items_parsed:`) to confirm `items_processed = state.items_parsed` is the correct full set to iterate for the upsert — do not use only `relevant_items` here, that would miss writing rows for rejected items and defeat the delivery-cursor purpose entirely.

- [ ] **Step 5: Same change in `classify_with_llm`**

Apply the identical pattern (unique_items assignment + upsert loop over the full input set) at the equivalent point in `classify_with_llm` — find its `state.relevant_items = relevant_items` line and insert the same two additions after it.

- [ ] **Step 6: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_classify.py -v --no-cov`
Expected: PASS (full file).

- [ ] **Step 7: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -20`
Expected: no new failures beyond baseline. The end-to-end `DeliveryGraph` invocation (deferred from Task 10's Step 14) should now actually work if exercised — not required as a new test here, but confirm no regression.

- [ ] **Step 8: Commit**

```bash
git add src/tenderai_bf/agents/nodes/classify.py tests/nodes/test_classify.py
git commit -m "feat(pipeline): classify_node writes CompanyNoticeStatus, sets unique_items

Every classified item (relevant or not) gets an upserted CompanyNoticeStatus
row with delivered_at=NULL — required so select_new_notices' absence-based
cursor doesn't reclassify rejected items forever. state.unique_items is set
to the same relevant_items list, satisfying summarize_node/compose_report_node's
existing dependency without touching either node (delivery has no separate
dedup step)."
```

---

## Task 12: `email_report_node` — company-scoped recipients

**Files:**
- Modify: `src/tenderai_bf/agents/nodes/email_report.py`
- Test: new test in `tests/nodes/` (check for an existing `test_email_report.py` first)

**Interfaces:**
- Consumes: `TenderAIState.company_id`.
- Produces: `email_report_node`'s `Recipient` query filters on `company_id` in addition to the existing `country_id`.

- [ ] **Step 1: Check for an existing test file**

Run: `ls tests/nodes/ | grep email_report`
If `tests/nodes/test_email_report.py` exists, read it in full and follow its existing patterns for Step 2 below rather than creating a new file.

- [ ] **Step 2: Write the failing test**

If no existing file, create `tests/nodes/test_email_report.py`:
```python
import os

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tenderai_bf.agents.graph import TenderAIState
from tenderai_bf.agents.nodes.email_report import email_report_node
from tenderai_bf.db import Base
from tenderai_bf.models import Recipient


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([
        Recipient(id=1, email="yulcom@example.com", country_id=1, company_id=1, enabled=True),
        Recipient(id=2, email="other-company@example.com", country_id=1, company_id=2, enabled=True),
    ])
    session.commit()

    def _fake_get_db_context():
        class _Ctx:
            def __enter__(self):
                return session
            def __exit__(self, *a):
                pass
        return _Ctx()

    monkeypatch.setattr(
        "tenderai_bf.agents.nodes.email_report.get_db_context", _fake_get_db_context
    )
    yield session
    session.close()


@patch("tenderai_bf.agents.nodes.email_report.send_report_email")
@patch("tenderai_bf.agents.nodes.email_report.cfg")
def test_email_report_filters_recipients_by_company(mock_cfg, mock_send, db_session):
    mock_cfg.return_value = None  # no extra "to_address" recipient
    mock_send.return_value = True

    state = TenderAIState(
        country_id=1,
        company_id=1,
        report_bytes=b"fake docx",
        report_url="https://minio/report.docx",
    )
    email_report_node(state)

    sent_recipients = mock_send.call_args.kwargs["recipients"]
    assert "yulcom@example.com" in sent_recipients
    assert "other-company@example.com" not in sent_recipients
```

(If `Recipient` doesn't already have a `company_id` column in this branch's checked-out code, this confirms Task 2 of the earlier Plan #1 merge — check `grep -n "company_id" src/tenderai_bf/models.py | grep -A2 -B2 Recipient` if the fixture fails to construct.)

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest tests/nodes/test_email_report.py -v --no-cov -k filters_recipients_by_company`
Expected: FAIL — both recipients are returned (no `company_id` filter yet).

- [ ] **Step 4: Add the `company_id` filter**

Current (`email_report.py`):
```python
        with get_db_context() as _db:
            db_recipients = (
                _db.query(Recipient)
                .filter(
                    Recipient.country_id == state.country_id,
                    Recipient.enabled == True,  # noqa: E712
                )
                .all()
            )
```

Replace with:
```python
        with get_db_context() as _db:
            db_recipients = (
                _db.query(Recipient)
                .filter(
                    Recipient.country_id == state.country_id,
                    Recipient.company_id == state.company_id,
                    Recipient.enabled == True,  # noqa: E712
                )
                .all()
            )
```

Leave everything else in the function unchanged — `cfg(state, "email", "to_address")` stays as-is per this plan's Global Constraints (country-level, orthogonal to company scoping).

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/nodes/test_email_report.py -v --no-cov`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline. Note: harvest-mode `TenderAIGraph` no longer includes `email_report_node` at all (Task 9), so this change only affects the delivery graph's usage — no harvest-side impact possible.

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/agents/nodes/email_report.py tests/nodes/test_email_report.py
git commit -m "fix(pipeline): email_report_node scopes Recipient query by company_id

Recipients now filtered by both country_id and company_id — without this,
a delivery run for company A would email company B's recipients too."
```

---

## Task 13: `cli.py run-once` — add `--company`/`--company-code`, combined run

**Files:**
- Modify: `src/tenderai_bf/cli.py`
- Test: new test in `tests/` (check for an existing CLI test first)

**Interfaces:**
- Consumes: `get_delivery_pipeline()` (Task 10), `Company.slug`.
- Produces: `run_once` now requires `--company-id` or `--company-code` alongside `--country-id`/`--country-code`; runs harvest then delivery for that (country, company) pair.

- [ ] **Step 1: Check for an existing CLI test**

Run: `grep -rln "run_once\|run-once" tests/`
Read any hits in full before writing new tests, to match existing patterns (e.g. `CliRunner` usage from `click.testing`).

- [ ] **Step 2: Write the failing test**

Add to `tests/test_smoke.py` (or the file found in Step 1 — follow its existing `CliRunner`/mocking conventions):
```python
def test_run_once_requires_company():
    from click.testing import CliRunner
    from tenderai_bf.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["run-once", "--country-code", "BF"])
    assert result.exit_code != 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest tests/test_smoke.py -v --no-cov -k run_once_requires_company`
Expected: FAIL — `run_once` currently succeeds (or attempts to) without `--company-code`/`--company-id`.

- [ ] **Step 4: Update `run_once`**

Current:
```python
@main.command()
@click.option("--triggered-by", default="manual", help="Who triggered this run")
@click.option("--user", default=None, help="User who triggered this run")
@click.option(
    "--country-id", default=1, type=int, help="Country ID to run pipeline for"
)
@click.option(
    "--country-code",
    default=None,
    help="ISO-2 country code (CA, BF, CI, SN…) — overrides --country-id",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Test mode: send the report only to the admin email (TENDERAI_ADMIN_EMAIL), not all recipients",
)
def run_once(triggered_by: str, user: str | None, country_id: int, country_code: str | None, test_mode: bool):
    """Execute the pipeline once and generate a report."""

    click.echo("🚀 Starting TenderAI BF pipeline..." + (" [MODE TEST]" if test_mode else ""))

    try:
        # Resolve country code → country ID when --country-code is provided
        if country_code:
            from sqlalchemy import text as _text
            _engine = get_engine()
            with _engine.connect() as _conn:
                _row = _conn.execute(
                    _text("SELECT id, name FROM countries WHERE UPPER(code) = UPPER(:code)"),
                    {"code": country_code},
                ).fetchone()
            if not _row:
                click.echo(f"❌ Unknown country code '{country_code}'. Check the countries table.")
                sys.exit(1)
            country_id = _row[0]
            click.echo(f"   Country: {_row[1]} (code={country_code.upper()}, id={country_id})")

        # Get pipeline
        pipeline = get_pipeline()

        # Execute pipeline (returns a TenderAIState)
        result = pipeline.run(
            country_id=country_id,
            triggered_by=triggered_by,
            triggered_by_user=user,
            test_mode=test_mode,
        )

        errors = result.errors
        warnings = result.warnings
        stats = result.stats.dict()
        report_url = result.report_url
        email_status = result.email_status or {}

        if result.error_occurred:
            click.echo(f"❌ Pipeline failed with {len(errors)} error(s)")
            for error in errors:
                click.echo(f"   • [{error['step']}] {error['error']}")
            sys.exit(1)

        if warnings:
            click.echo(f"⚠️  Pipeline completed with {len(warnings)} warning(s)")
            for w in warnings:
                click.echo(f"   • [{w['step']}] {w['warning']}")
        else:
            click.echo("✅ Pipeline completed successfully!")

        click.echo(f"   • Sources checked: {stats.get('sources_checked', 0)}")
        click.echo(f"   • Items found: {stats.get('items_parsed', 0)}")
        click.echo(f"   • Relevant items: {stats.get('relevant_items', 0)}")
        click.echo(f"   • Unique items: {stats.get('unique_items', 0)}")
        click.echo(f"   • Execution time: {stats.get('total_time_seconds', 0):.1f}s")

        if report_url:
            click.echo(f"   • Report URL: {report_url}")

        if email_status.get("success"):
            click.echo(
                f"   • Email sent to {email_status.get('recipients_count', 0)} recipient(s)"
            )
        elif email_status and not email_status.get("skipped"):
            click.echo("   • Email delivery failed (report still available on MinIO)")

    except KeyboardInterrupt:
        click.echo("\n⚠️ Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Pipeline failed: {e}")
        logger.error("CLI run-once failed", error=str(e), exc_info=True)
        sys.exit(1)
```

Replace with:
```python
@main.command()
@click.option("--triggered-by", default="manual", help="Who triggered this run")
@click.option("--user", default=None, help="User who triggered this run")
@click.option(
    "--country-id", default=None, type=int, help="Country ID to run pipeline for"
)
@click.option(
    "--country-code",
    default=None,
    help="ISO-2 country code (CA, BF, CI, SN…) — overrides --country-id",
)
@click.option(
    "--company-id", default=None, type=int, help="Company ID to deliver to"
)
@click.option(
    "--company-code",
    default=None,
    help="Company slug (yulcom…) — overrides --company-id",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Test mode: send the report only to the admin email (TENDERAI_ADMIN_EMAIL), not all recipients",
)
def run_once(
    triggered_by: str,
    user: str | None,
    country_id: int | None,
    country_code: str | None,
    company_id: int | None,
    company_code: str | None,
    test_mode: bool,
):
    """Run harvest for one country, then delivery for one company, in sequence."""

    if country_id is None and not country_code:
        click.echo("❌ --country-id or --country-code is required")
        sys.exit(1)
    if company_id is None and not company_code:
        click.echo("❌ --company-id or --company-code is required")
        sys.exit(1)

    click.echo("🚀 Starting TenderAI BF pipeline..." + (" [MODE TEST]" if test_mode else ""))

    try:
        from sqlalchemy import text as _text
        _engine = get_engine()

        # Resolve country code → country ID when --country-code is provided
        if country_code:
            with _engine.connect() as _conn:
                _row = _conn.execute(
                    _text("SELECT id, name FROM countries WHERE UPPER(code) = UPPER(:code)"),
                    {"code": country_code},
                ).fetchone()
            if not _row:
                click.echo(f"❌ Unknown country code '{country_code}'. Check the countries table.")
                sys.exit(1)
            country_id = _row[0]
            click.echo(f"   Country: {_row[1]} (code={country_code.upper()}, id={country_id})")

        # Resolve company code → company ID when --company-code is provided
        if company_code:
            with _engine.connect() as _conn:
                _row = _conn.execute(
                    _text("SELECT id, name FROM companies WHERE UPPER(slug) = UPPER(:slug)"),
                    {"slug": company_code},
                ).fetchone()
            if not _row:
                click.echo(f"❌ Unknown company code '{company_code}'. Check the companies table.")
                sys.exit(1)
            company_id = _row[0]
            click.echo(f"   Company: {_row[1]} (slug={company_code.lower()}, id={company_id})")

        # --- Harvest ---
        harvest_pipeline = get_pipeline()
        harvest_result = harvest_pipeline.run(
            country_id=country_id,
            triggered_by=triggered_by,
            triggered_by_user=user,
        )

        if harvest_result.error_occurred:
            click.echo(f"❌ Harvest failed with {len(harvest_result.errors)} error(s)")
            for error in harvest_result.errors:
                click.echo(f"   • [{error['step']}] {error['error']}")
            sys.exit(1)

        harvest_stats = harvest_result.stats.dict()
        click.echo("✅ Harvest completed")
        click.echo(f"   • Sources checked: {harvest_stats.get('sources_checked', 0)}")
        click.echo(f"   • Items parsed: {harvest_stats.get('items_parsed', 0)}")
        click.echo(f"   • Unique items: {harvest_stats.get('unique_items', 0)}")
        click.echo(f"   • Notices persisted: {harvest_stats.get('notices_persisted', 0)}")

        # --- Delivery ---
        from .agents import get_delivery_pipeline

        delivery_pipeline = get_delivery_pipeline()
        delivery_result = delivery_pipeline.run(
            company_id=company_id,
            country_id=country_id,
            triggered_by=triggered_by,
            triggered_by_user=user,
            test_mode=test_mode,
        )

        errors = delivery_result.errors
        warnings = delivery_result.warnings
        stats = delivery_result.stats.dict()
        report_url = delivery_result.report_url
        email_status = delivery_result.email_status or {}

        if delivery_result.error_occurred:
            click.echo(f"❌ Delivery failed with {len(errors)} error(s)")
            for error in errors:
                click.echo(f"   • [{error['step']}] {error['error']}")
            sys.exit(1)

        if warnings:
            click.echo(f"⚠️  Delivery completed with {len(warnings)} warning(s)")
            for w in warnings:
                click.echo(f"   • [{w['step']}] {w['warning']}")
        else:
            click.echo("✅ Delivery completed successfully!")

        click.echo(f"   • Relevant items: {stats.get('relevant_items', 0)}")
        click.echo(f"   • Execution time: {stats.get('total_time_seconds', 0):.1f}s")

        if report_url:
            click.echo(f"   • Report URL: {report_url}")

        if email_status.get("success"):
            click.echo(
                f"   • Email sent to {email_status.get('recipients_count', 0)} recipient(s)"
            )
        elif email_status and not email_status.get("skipped"):
            click.echo("   • Email delivery failed (report still available on MinIO)")

    except KeyboardInterrupt:
        click.echo("\n⚠️ Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Pipeline failed: {e}")
        logger.error("CLI run-once failed", error=str(e), exc_info=True)
        sys.exit(1)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/test_smoke.py -v --no-cov -k run_once`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline. `test_cli_commands` (a known pre-existing failure per the sous-projet B baseline) may still fail for its own pre-existing reason — do not attempt to fix that here, it's out of scope.

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/cli.py tests/test_smoke.py
git commit -m "feat(cli): run-once requires --country and --company, runs harvest then delivery

Both dimensions are now mandatory (by id or code/slug) — no standalone
harvest-only invocation via run-once. A single call runs harvest for the
given country, then delivery for the given company scoped to that same
country (not the company's full subscription list — that's the scheduled
delivery job's job, next task)."
```

---

## Task 14: Scheduler — decoupled harvest and delivery job families

**Files:**
- Modify: `src/tenderai_bf/scheduler/schedule.py`
- Test: `tests/` (check for existing scheduler tests first)

**Interfaces:**
- Consumes: `get_delivery_pipeline()` (Task 10), `CompanyStore.get_all_with_fallback`, `Company`, `CompanyCountrySubscription`.
- Produces: `reschedule_company_delivery_job(company_id, company_slug, scheduler_cfg)`, `scheduled_company_delivery_run(company_id)`, and a company-iterating block in `start_scheduler()` — mirroring the existing country/harvest equivalents exactly.

- [ ] **Step 1: Check for existing scheduler tests**

Run: `grep -rln "scheduler\|reschedule_country_job\|scheduled_pipeline_run" tests/ | grep -v nodes`
Read any hits before writing new tests.

- [ ] **Step 2: Write the failing test**

Create `tests/test_scheduler_delivery.py` (or add to the file found in Step 1):
```python
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")


@patch("tenderai_bf.scheduler.schedule.get_scheduler_instance")
def test_reschedule_company_delivery_job_no_op_when_scheduler_not_started(mock_get_sched):
    from tenderai_bf.scheduler.schedule import reschedule_company_delivery_job

    mock_get_sched.return_value = None
    # Must not raise even though the scheduler hasn't started.
    reschedule_company_delivery_job(1, "yulcom", {"enabled": True, "cron_schedule": "0 8 * * *"})


@patch("tenderai_bf.scheduler.schedule.get_delivery_pipeline")
def test_scheduled_company_delivery_run_iterates_enabled_subscriptions(mock_get_pipeline):
    from tenderai_bf.scheduler.schedule import scheduled_company_delivery_run

    mock_pipeline = MagicMock()
    mock_result = MagicMock(error_occurred=False, warnings=[])
    mock_pipeline.run.return_value = mock_result
    mock_get_pipeline.return_value = mock_pipeline

    with patch("tenderai_bf.scheduler.schedule.get_session_factory") as mock_sf:
        mock_session = MagicMock()
        mock_sf.return_value.return_value = mock_session
        mock_sub_1 = MagicMock(country_id=1, enabled=True)
        mock_sub_2 = MagicMock(country_id=2, enabled=True)
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_sub_1, mock_sub_2,
        ]

        scheduled_company_delivery_run(company_id=1)

    assert mock_pipeline.run.call_count == 2
    called_country_ids = {c.kwargs["country_id"] for c in mock_pipeline.run.call_args_list}
    assert called_country_ids == {1, 2}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `poetry run pytest tests/test_scheduler_delivery.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'reschedule_company_delivery_job'`

- [ ] **Step 4: Add `reschedule_company_delivery_job` and `scheduled_company_delivery_run`**

Add to `src/tenderai_bf/scheduler/schedule.py`, right after the existing `reschedule_country_job`/`scheduled_pipeline_run` pair:

```python
def reschedule_company_delivery_job(
    company_id: int, company_slug: str, scheduler_cfg: dict
) -> None:
    """Remove and optionally re-add the APScheduler job for a company's delivery.

    Called by the settings API when a company's scheduler section is updated.
    No-op if the scheduler hasn't been started yet. Mirrors reschedule_country_job.
    """
    scheduler = get_scheduler_instance()
    if scheduler is None:
        return

    job_id = f"delivery_{company_slug}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not scheduler_cfg.get("enabled", True):
        return

    cron = scheduler_cfg.get("cron_schedule") or settings.scheduler.cron_schedule
    trigger = _make_trigger(
        cron,
        scheduler_cfg.get("timezone", settings.scheduler.timezone),
    )
    scheduler.add_job(
        scheduled_company_delivery_run,
        args=[company_id],
        trigger=trigger,
        id=job_id,
        name=f"Delivery {company_slug}",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=scheduler_cfg.get("max_concurrent_runs", 1),
    )
    logger.info(
        "Company delivery job rescheduled",
        company_slug=company_slug,
        cron=scheduler_cfg["cron_schedule"],
    )


def scheduled_company_delivery_run(company_id: int) -> None:
    """Execute delivery for every enabled (company, country) subscription."""

    from ..models import CompanyCountrySubscription

    logger.info("Starting scheduled company delivery run", company_id=company_id)

    SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
    db_session = SessionLocal()
    try:
        subscriptions = (
            db_session.query(CompanyCountrySubscription)
            .filter(
                CompanyCountrySubscription.company_id == company_id,
                CompanyCountrySubscription.enabled == True,  # noqa: E712
            )
            .all()
        )
    finally:
        db_session.close()

    pipeline = get_delivery_pipeline()
    for sub in subscriptions:
        try:
            result = pipeline.run(
                company_id=company_id, country_id=sub.country_id, triggered_by="scheduler"
            )
            if result.error_occurred:
                logger.error(
                    "Scheduled company delivery run failed",
                    company_id=company_id,
                    country_id=sub.country_id,
                    errors_count=len(result.errors),
                    run_id=result.run_id,
                )
            elif result.warnings:
                logger.warning(
                    "Scheduled company delivery run completed with warnings",
                    company_id=company_id,
                    country_id=sub.country_id,
                    run_id=result.run_id,
                    warnings_count=len(result.warnings),
                )
            else:
                logger.info(
                    "Scheduled company delivery run completed",
                    company_id=company_id,
                    country_id=sub.country_id,
                    run_id=result.run_id,
                )
        except Exception as e:
            logger.error(
                "Scheduled company delivery run exception",
                company_id=company_id,
                country_id=sub.country_id,
                error=str(e),
                exc_info=True,
            )
```

Update the module-level import (top of `schedule.py`):
```python
from ..agents import get_pipeline
```
becomes:
```python
from ..agents import get_delivery_pipeline, get_pipeline
```

Also add `from ..db import get_session_factory` to the module-level imports (`scheduled_company_delivery_run` needs it; check it isn't already imported — `start_scheduler()` currently imports it locally inside the function, at `from ..db import get_session_factory`, so a module-level import is a small consolidation, not strictly required — either add it at module level and remove the now-redundant local import inside `start_scheduler()`, or keep `scheduled_company_delivery_run`'s own local `from ..db import get_session_factory` import matching the existing local-import style. Prefer matching the existing local-import style for consistency: add `from ..db import get_session_factory` as a local import inside `scheduled_company_delivery_run`, not at module level).

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/test_scheduler_delivery.py -v --no-cov`
Expected: PASS

- [ ] **Step 6: Add the company-iterating block to `start_scheduler()`**

Current `start_scheduler()` (relevant section, after the country-job loop, before `logger.info("Scheduler configured", ...)`):
```python
        if run_on_startup:
            logger.info("Running pipeline on startup", country_code=country.code)
            scheduled_pipeline_run(country_id)

    logger.info("Scheduler configured", jobs_count=len(scheduler.get_jobs()))
```

Insert a company-iterating block between the country loop's closing and the "Scheduler configured" log line. First, update the country-loading section at the top of `start_scheduler()`:

Current:
```python
    # Load active countries
    from ..country_store import CountryStore
    from ..db import get_session_factory
    from ..models import Country

    SessionLocal = get_session_factory()
    db_session = SessionLocal()
    try:
        countries = db_session.query(Country).filter(Country.active == True).all()
        country_configs = {
            c.id: (c, CountryStore.get_all_with_fallback(db_session, c.id))
            for c in countries
        }
    finally:
        db_session.close()
```

Replace with:
```python
    # Load active countries
    from ..company_store import CompanyStore
    from ..country_store import CountryStore
    from ..db import get_session_factory
    from ..models import Company, Country

    SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
    db_session = SessionLocal()
    try:
        countries = db_session.query(Country).filter(Country.active == True).all()  # noqa: E712
        country_configs = {
            c.id: (c, CountryStore.get_all_with_fallback(db_session, c.id))
            for c in countries
        }
        companies = db_session.query(Company).filter(Company.active == True).all()  # noqa: E712
        company_configs = {
            c.id: (c, CompanyStore.get_all_with_fallback(db_session, c.id))
            for c in companies
        }
    finally:
        db_session.close()
```

Then insert, right after the country loop's closing (`if run_on_startup: ... scheduled_pipeline_run(country_id)`), before `logger.info("Scheduler configured", ...)`:
```python
    for company_id, (company, config) in company_configs.items():
        sched_cfg = config.get("scheduler", {})
        cron = sched_cfg.get("cron_schedule", _default_cron)
        tz_str = sched_cfg.get("timezone", _default_tz)
        enabled = sched_cfg.get("enabled", True)
        max_inst = sched_cfg.get(
            "max_concurrent_runs", settings.scheduler.max_concurrent_runs
        )
        run_on_startup = sched_cfg.get("run_on_startup", False)

        if not enabled:
            logger.info(
                "Company delivery scheduler disabled, skipping", company_slug=company.slug
            )
            continue

        trigger = _make_trigger(cron, tz_str)
        scheduler.add_job(
            scheduled_company_delivery_run,
            args=[company_id],
            trigger=trigger,
            id=f"delivery_{company.slug}",
            name=f"Delivery {company.name}",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=max_inst,
        )
        logger.info(
            "Delivery scheduler job added",
            company_slug=company.slug,
            cron_schedule=cron,
            timezone=tz_str,
        )

        if run_on_startup:
            logger.info("Running delivery on startup", company_slug=company.slug)
            scheduled_company_delivery_run(company_id)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `poetry run pytest tests/test_scheduler_delivery.py -v --no-cov`
Expected: PASS (full file).

- [ ] **Step 8: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -15`
Expected: no new failures beyond baseline.

- [ ] **Step 9: Commit**

```bash
git add src/tenderai_bf/scheduler/schedule.py tests/test_scheduler_delivery.py
git commit -m "feat(scheduler): add decoupled per-company delivery job family

reschedule_company_delivery_job/scheduled_company_delivery_run mirror the
existing per-country harvest job family exactly. start_scheduler() now
registers both families independently — no ordering dependency between
harvest and delivery cron jobs, matching the design spec."
```

---

## Task 15: Preserve email delivery for the two existing manual-trigger API endpoints

**Files:**
- Modify: `src/tenderai_bf/api/routers/countries.py`
- Modify: `src/tenderai_bf/api/routers/runs.py`
- Test: `tests/api/test_countries_run_trigger.py` (new)

**Interfaces:**
- Consumes: `get_delivery_pipeline()` (Task 10).
- Produces: both endpoints' background pipeline trigger now runs harvest, then delivery for YULCOM (looked up by slug), preserving today's "run now → recipients get an email" behavior. This is a deliberate, explicitly-scoped exception to this plan's stated "only touches agents/, scheduler/, cli.py" boundary — necessary because `TenderAIGraph` (Task 9) stopped sending email at all, and these two endpoints are real, currently-working, user-facing triggers that would otherwise silently regress. Proper company selection for these endpoints is real Auth/API-plan scope (a later plan); hardcoding YULCOM here is a documented stopgap, not a design decision to build on.

- [ ] **Step 1: Write the failing test for `countries.py`**

`tests/api/test_countries_endpoints.py`'s existing `client` fixture (read the file first) is a lightweight, auth-tolerant style (`_get_token()` falls back to a fake token, tests just assert status codes in a tolerant set like `(200, 401, 403)`) — it cannot exercise this endpoint's actual `admin`-gated logic, since it never seeds a real authenticated admin user. `tests/api/test_users.py` has the real pattern this needs (seed a `User(role="super_admin")`, log in via `/api/v1/admin/login/simple` for a genuine JWT, then call the endpoint with it — read `tests/api/test_users.py`'s `admin_token` fixture and `test_create_user_sends_email` for the exact pattern before writing this test). Create `tests/api/test_countries_run_trigger.py` following that proven pattern instead of `test_countries_endpoints.py`'s lighter one:

```python
import os
import uuid
from unittest.mock import MagicMock, patch

os.environ.setdefault("TENDERAI_JWT_SECRET", "test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx")
os.environ.setdefault("TENDERAI_ADMIN_PASSWORD", "test-admin-password-not-real")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tenderai_bf.api.dependencies import get_password_hash
from tenderai_bf.api.main import app
from tenderai_bf.db import get_db
from tenderai_bf.models import Base, Company, Country, User


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token(client, db_session):
    admin = User(
        id=str(uuid.uuid4()),
        username="admin",
        email="admin@test.com",
        hashed_password=get_password_hash("adminpass123"),
        role="super_admin",
        is_active=True,
        password_reset_required=False,
    )
    db_session.add(admin)
    db_session.commit()

    resp = client.post(
        "/api/v1/admin/login/simple",
        json={"username": "admin", "password": "adminpass123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@patch("tenderai_bf.agents.get_delivery_pipeline")
@patch("tenderai_bf.agents.get_pipeline")
def test_trigger_run_calls_both_harvest_and_delivery(
    mock_get_pipeline, mock_get_delivery_pipeline, client, admin_token, db_session
):
    country = Country(id=1, name="Burkina Faso", code="BF", locale="fr", active=True)
    company = Company(id=1, name="YULCOM Technologies", slug="yulcom", active=True)
    db_session.add_all([country, company])
    db_session.commit()

    mock_harvest_pipeline = MagicMock()
    mock_harvest_pipeline.run.return_value = MagicMock(error_occurred=False)
    mock_get_pipeline.return_value = mock_harvest_pipeline

    mock_delivery_pipeline = MagicMock()
    mock_get_delivery_pipeline.return_value = mock_delivery_pipeline

    resp = client.post(
        "/api/v1/admin/countries/1/run",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 202

    assert mock_harvest_pipeline.run.called
    assert mock_delivery_pipeline.run.called
    delivery_kwargs = mock_delivery_pipeline.run.call_args.kwargs
    assert delivery_kwargs["company_id"] == 1
    assert delivery_kwargs["country_id"] == 1
```

Note: `get_pipeline`/`get_delivery_pipeline` are patched at `tenderai_bf.agents.get_pipeline`/`get_delivery_pipeline` (the package-level re-export from `agents/__init__.py`, Task 10 Step 13), not at `tenderai_bf.agents.graph.get_pipeline` — `countries.py`'s updated code (Step 3 below) imports via `from ...agents import get_delivery_pipeline, get_pipeline`, so patching must target where the name is *looked up from* at call time, which for a local `from ... import` inside a function body is the `agents` package namespace itself. Verify this patch target resolves correctly when you run the test — if `@patch` reports the target doesn't exist, confirm the exact import path Step 3 actually uses and patch that instead.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/api/test_countries_run_trigger.py -v --no-cov`
Expected: FAIL — only `mock_harvest_pipeline.run` is called; `mock_delivery_pipeline.run.called` is `False`.

- [ ] **Step 3: Update `countries.py`'s trigger endpoint**

Current:
```python
    _get_country_or_404(country_id, db)
    from ...agents import get_pipeline

    def _run():
        get_pipeline().run(
            country_id=country_id,
            triggered_by="api",
            triggered_by_user=user["username"],
        )

    background_tasks.add_task(_run)
    return {"status": "accepted", "country_id": country_id}
```

Replace with:
```python
    _get_country_or_404(country_id, db)
    from ...agents import get_delivery_pipeline, get_pipeline

    def _run():
        get_pipeline().run(
            country_id=country_id,
            triggered_by="api",
            triggered_by_user=user["username"],
        )
        # Stopgap until the Auth/API plan adds company selection to this
        # endpoint: deliver to YULCOM (company zero) so this manual trigger
        # keeps sending email as it did before the pipeline split.
        from ...db import get_db_context
        from ...models import Company

        with get_db_context() as _db:
            yulcom = _db.query(Company).filter(Company.slug == "yulcom").first()
        if yulcom:
            get_delivery_pipeline().run(
                company_id=yulcom.id,
                country_id=country_id,
                triggered_by="api",
                triggered_by_user=user["username"],
            )
        else:
            logger.error(
                "YULCOM company not found — skipping delivery after manual harvest trigger",
                country_id=country_id,
            )

    background_tasks.add_task(_run)
    return {"status": "accepted", "country_id": country_id}
```

Check `countries.py` already imports `logger`/`get_logger` (it should, per this codebase's convention — verify with `grep -n "^logger = " src/tenderai_bf/api/routers/countries.py`).

- [ ] **Step 4: Update `runs.py`'s trigger endpoint**

Current `run_pipeline()` inner function:
```python
    def run_pipeline():
        try:
            # Prepare sources override if specified
            sources_override = None
            if request.sources:
                # TODO: Load full source data from DB based on names/IDs
                sources_override = request.sources

            result = pipeline.run(
                country_id=request.country_id,
                triggered_by=request.triggered_by,
                triggered_by_user=triggered_by_user,
                sources_override=sources_override,
                send_email=request.send_email,
            )

            # result is now always a TenderAIState (see TenderAIGraph.run)
            if result.error_occurred:
                run_status = "failed"
            elif result.warnings:
                run_status = "completed_with_warnings"
            else:
                run_status = "completed"

            logger.info(
                "Pipeline run completed",
                run_id=result.run_id,
                status=run_status,
                items=result.stats.unique_items,
                warnings_count=len(result.warnings),
            )

        except Exception as e:
            logger.error("Pipeline run failed", run_id=run_id, error=str(e), exc_info=e)
```

Note `pipeline.run(...)` no longer accepts `sources_override`/`send_email` meaningfully post-split (Task 9 keeps them accepted-but-unused on `TenderAIGraph.run()` — check that this is still true; if `sources_override` genuinely still works for harvest, keep passing it, but `send_email` has no effect on harvest anymore). Replace with:
```python
    def run_pipeline():
        try:
            # Prepare sources override if specified
            sources_override = None
            if request.sources:
                # TODO: Load full source data from DB based on names/IDs
                sources_override = request.sources

            harvest_result = pipeline.run(
                country_id=request.country_id,
                triggered_by=request.triggered_by,
                triggered_by_user=triggered_by_user,
                sources_override=sources_override,
            )

            if harvest_result.error_occurred:
                logger.error(
                    "Pipeline run failed",
                    run_id=harvest_result.run_id,
                    errors_count=len(harvest_result.errors),
                )
                return

            result = harvest_result
            if request.send_email:
                # Stopgap until the Auth/API plan adds company selection to
                # this endpoint: deliver to YULCOM (company zero) so this
                # manual trigger keeps sending email as it did before the
                # pipeline split.
                from ...db import get_db_context
                from ...models import Company

                with get_db_context() as _db:
                    yulcom = _db.query(Company).filter(Company.slug == "yulcom").first()
                if yulcom:
                    result = get_delivery_pipeline().run(
                        company_id=yulcom.id,
                        country_id=request.country_id,
                        triggered_by=request.triggered_by,
                        triggered_by_user=triggered_by_user,
                    )
                else:
                    logger.error(
                        "YULCOM company not found — skipping delivery after manual harvest trigger",
                        country_id=request.country_id,
                    )

            if result.error_occurred:
                run_status = "failed"
            elif result.warnings:
                run_status = "completed_with_warnings"
            else:
                run_status = "completed"

            logger.info(
                "Pipeline run completed",
                run_id=result.run_id,
                status=run_status,
                warnings_count=len(result.warnings),
            )

        except Exception as e:
            logger.error("Pipeline run failed", run_id=run_id, error=str(e), exc_info=e)
```

Add the import at the top of the file:
```python
from ...agents import get_delivery_pipeline, get_pipeline
```
(replacing whatever the current `get_pipeline`-only import line is — check `grep -n "from \.\.\.agents import" src/tenderai_bf/api/routers/runs.py`).

Note: `result.stats.unique_items` was removed from the log call above (harvest's `result` before delivery runs doesn't necessarily have a meaningful `unique_items` count in the same sense post-split; if `send_email=False`, `result` stays the harvest result and `result.stats` still has whatever fields `RunStatistics` defines — check `stats.unique_items` still exists on `RunStatistics` before removing this log field entirely; if it does, it's fine to keep `items=result.stats.unique_items` in the log call, this plan doesn't require removing it, just noting it may now describe harvest-only output when `send_email=False`).

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/api/test_countries_run_trigger.py -v --no-cov`
Expected: PASS (full file).

- [ ] **Step 6: Run the full test suite**

Run: `poetry run pytest tests/ -v --no-cov 2>&1 | tail -20`
Expected: no new failures beyond baseline. Confirmed while writing this task (via `git grep -rln "trigger_run\|/trigger" tests/api/`, zero hits): no existing test targets `runs.py`'s `/trigger` endpoint at all, so there is nothing there to break or update — `runs.py`'s change in this task is verified only by the full-suite run finding no new failures, not by a dedicated new test (adding one is optional polish outside this plan's stated goal, not required for this task's completion).

- [ ] **Step 7: Commit**

```bash
git add src/tenderai_bf/api/routers/countries.py src/tenderai_bf/api/routers/runs.py tests/api/test_countries_run_trigger.py
git commit -m "fix(api): preserve email delivery for existing manual pipeline triggers

TenderAIGraph no longer sends email (pipeline split, Task 9) — these two
endpoints previously relied on that. Both now run harvest then,
conditionally, delivery for YULCOM (hardcoded lookup by slug) as a
documented stopgap, preserving today's 'trigger a run, recipients get an
email' behavior until the Auth/API plan adds real company selection to
these endpoints."
```

---

## Task 16: Final verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-15 complete.
- Produces: confirmation this plan's goal is met — `ruff check` clean, full test suite green (matching baseline), and a manual harvest→persist→deliver smoke check.

- [ ] **Step 1: `ruff check` clean**

```bash
TENDERAI_JWT_SECRET="test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx" \
  TENDERAI_ADMIN_PASSWORD="test-admin-password-not-real" \
  poetry run ruff check src tests
```
Expected: no NEW violations introduced by this plan's own edits (pre-existing violations in files this plan never touches — e.g. `tests/conftest.py`'s S108, `test_company_store*.py`'s E402, both flagged during the earlier chantier-3 audit as main's own unreviewed debt — are not this plan's concern to fix).

- [ ] **Step 2: `ruff format --check`**

```bash
poetry run ruff format --check src tests
```
If new files from this plan aren't formatted, run `poetry run ruff format src tests` and commit separately (mirror sous-projet B's Task 5 pattern — pure style, no semantic changes, verify with `git diff` before committing).

- [ ] **Step 3: Full test suite, strict comparison against this plan's own start-of-plan baseline**

```bash
TENDERAI_JWT_SECRET="test-jwt-secret-not-used-for-real-auth-only-pytest-xxxxxxxx" \
  TENDERAI_ADMIN_PASSWORD="test-admin-password-not-real" \
  poetry run pytest tests/ -v --no-cov > /tmp/pipeline-split-test-after.txt 2>&1
echo "exit code: $?" >> /tmp/pipeline-split-test-after.txt
tail -20 /tmp/pipeline-split-test-after.txt
```
Expected: pass count has grown by roughly the number of new tests this plan added (Tasks 1-15 combined); no test that was passing before this plan started now fails, except any test this plan's own tasks deliberately updated (Tasks 6, 7, 9, 12, 13, 15's updated assertions) — those changes were already verified task-by-task, this is a final holistic check, not a re-litigation.

- [ ] **Step 4: Manual harvest → persist → deliver smoke check**

This requires a real Postgres/MinIO environment (per `docker compose exec api ...`, matching this repo's established local-run pattern) — not runnable from a SQLite-only worktree. Document the exact commands for whoever runs this against a real dev environment, do not attempt to execute them from this plan's own test suite:
```bash
docker compose exec api python -m tenderai_bf.cli run-once --country-code BF --company-code yulcom
```
Expected: harvest completes, echoes `Notices persisted: N` with `N > 0`; delivery completes, echoes relevant items count and either a report URL + successful email, or a clear warning if no recipients are configured. Then:
```bash
docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c \
  "SELECT count(*) FROM notices WHERE is_relevant IS NULL OR is_relevant = false;"
docker compose exec -T postgres psql -U tenderai -d tenderai_bf -c \
  "SELECT count(*) FROM company_notice_status WHERE company_id = (SELECT id FROM companies WHERE slug='yulcom');"
```
Confirms: `Notice.is_relevant` stayed at its column default (harvest never wrote it) and `CompanyNoticeStatus` rows exist for YULCOM's classified notices.

- [ ] **Step 5: Update `CLAUDE.md`'s pipeline description**

`CLAUDE.md`'s "LangGraph pipeline" section currently describes a single 10-node sequence ending in `email_report`. Update it to describe the harvest/delivery split:
```markdown
### LangGraph pipeline (`agents/graph.py`, `agents/delivery_graph.py`)

Two separate graphs share one `TenderAIState` (defined in `agents/graph.py`).

**Harvest graph** (`TenderAIGraph`, per-country, unchanged trigger cadence):
```
load_sources → fetch_listings → extract_item_links → fetch_items
→ parse_extract → deduplicate → persist_notices
```
Persists structural `Notice` rows only — no relevance judgment. Every step routes
through `_route_after_step`, short-circuiting to `error_handler` on
`error_occurred=True`/`should_continue=False`.

**Delivery graph** (`DeliveryGraph`, per-company, iterates that company's
subscribed countries when scheduled):
```
select_new_notices → classify → summarize → compose_report → email_report → mark_delivered
```
`select_new_notices` reads `Notice` rows with no `CompanyNoticeStatus` row for
this company yet — that absence is the delivery cursor. `classify` is the sole
place relevance is decided, per company, and writes the `CompanyNoticeStatus`
row that becomes that cursor going forward.

The global singleton `get_pipeline()` (harvest) and `get_delivery_pipeline()`
(delivery) are both thread-safe (double-checked locking).
```
Also update the "Node sequence" bullet under "Key subsystems" if `CLAUDE.md` has one referencing the old single sequence, and add `persist_notices.py`, `select_new_notices.py`, `mark_delivered.py`, `delivery_graph.py` to the `agents/nodes/` row's file list in the "Key subsystems" table.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for the harvest/delivery pipeline split"
```

- [ ] **Step 7: Summary**

This plan's goal — closing the original multi-company spec's Open Risk #1 (harvest-side pre-classification) and implementing its Section 2 (pipeline split) — is complete. `Notice` persistence, previously entirely absent from the running pipeline, now exists. Remaining scope from the original 5-section multi-company spec: Section 3 (Auth & API) and Section 4 (Frontend) — future plans, not started by this one. The YULCOM-hardcoding stopgap in Task 15's two API endpoints is a known, documented item for whichever future plan adds company selection to the admin API.

**Deliberately not addressed by this plan** (the original spec's own Open Risk #3, "worth a quick EXPLAIN check during implementation, not blocking design"): `select_new_notices_node`'s `NOT EXISTS` anti-join performance against real production volume. This plan's own test suite runs entirely against in-memory SQLite with a handful of rows per test — it cannot exercise this at realistic scale. Flag as a follow-up check once real `notices`/`company_notice_status` volume exists in a deployed environment (`EXPLAIN ANALYZE` the query from `select_new_notices.py` against production-shaped data); not a blocker for this plan's own completion.
