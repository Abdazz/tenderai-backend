# Multi-Company (Multi-Tenant) Support — Design Spec

**Date:** 2026-08-23
**Status:** Approved (pending final spec review)
**Refs:** `docs/superpowers/specs/2026-06-01-multi-country-design.md` (multi-country, which this spec builds on top of)

---

## Context

TenderAI BF is currently single-tenant: one company (YULCOM Technologies), multi-country. `Country` is the only isolation axis — sources, recipients, runs, and settings are scoped by `country_id`, but everything ultimately serves one organization. This spec adds `Company` as a new tenant axis above `Country`, so TenderAI can be operated as a real multi-client SaaS: each company sees only its own data, configures its own classification criteria, recipients, and branding, while sharing the underlying scraping infrastructure.

YULCOM itself becomes the first company registered in the new system (used for testing and as the reference tenant during migration).

---

## Scope Decisions (confirmed during brainstorming)

These were explicitly settled with the user and drive every section below:

1. **Company = external client.** True multi-tenant SaaS, not an internal YULCOM department split.
2. **Scraping/harvesting is shared, not per-company.** Each portal (DGCMEF, UNGM, Joffres.net, etc.) is scraped once per country. Only classification/relevance is company-specific.
3. **LLM keys stay global, managed by YULCOM.** Companies configure classification keywords/thresholds/prompts, not LLM provider credentials.
4. **The country/source catalog stays YULCOM-managed.** Companies subscribe to countries from the existing shared catalog (BF, CI, SN, CA, …); they don't define their own custom sources.
5. **Harvest and delivery are fully decoupled**, each with its own schedule (Approach 2, chosen over a simpler "fan-out inside one pipeline run" alternative). A company can have a different delivery cadence than the harvest cadence.
6. **One report per (company, country) per delivery run** — no merged multi-country digest, matching the existing `docx_report.py` shape.
7. **Companies are created by `super_admin` only.** No self-serve signup, no billing/quota system in this phase.

---

## Section 1 — Data Model

### New table: `Company`

```
id              Integer, PK, autoincrement
name            String(255), NOT NULL
slug            String(64),  NOT NULL, UNIQUE
active          Boolean,     NOT NULL, default True
logo_url        String(500), nullable
subject_prefix  String(100), nullable   -- email subject prefix, e.g. "[ACME]"
signature       String(255), nullable
created_at      DateTime,    NOT NULL, default now()
updated_at      DateTime,    NOT NULL, default now(), onupdate now()
```

### New table: `CompanyCountrySubscription`

```
company_id  Integer, FK → companies.id  }  composite PK
country_id  Integer, FK → countries.id  }
enabled     Boolean, NOT NULL, default True
created_at  DateTime, NOT NULL, default now()
```

Which countries (from the shared catalog) a company monitors. Disabling a subscription stops future delivery runs for that pair; historical `CompanyNoticeStatus`/reports are kept.

### New table: `CompanySettings`

Mirrors `CountrySettings`, one row per (company, section):

```
company_id  Integer, FK → companies.id  }  composite PK
section     String(64)                   }
data        JSON,     NOT NULL
updated_at  DateTime, server_default now(), onupdate now()
updated_by  Text,     nullable
```

Sections: `classification` (relevant_keywords, min_relevance_score, LLM prompts), `scheduler` (delivery cron_schedule, timezone, run_on_startup), `email` (subject_prefix override, signature override — falls back to `Company.subject_prefix`/`signature` columns above if absent). **Not** present: `llm` provider/keys (stay global `AppSettings`/env), `pipeline`/`rag` fetch mechanics (stay `CountrySettings`, shared).

Note: today `min_relevance_score` lives under `CountrySettings["pipeline"]`, not `["classification"]` (verified — `classify.py` reads it via `cfg(state, "pipeline", "min_relevance_score")`). At company level this spec consolidates it into `CompanySettings["classification"]` alongside `relevant_keywords`, since that's a more natural grouping for a fresh config surface — the implementation should read it from there for company-scoped classification, not replicate the country-level split.

When a company is created, `classification` and `scheduler` sections are seeded from `AppSettings` defaults (same pattern as country creation today).

### New table: `CompanyNoticeStatus`

The per-company classification result and delivery cursor — this is the core new mechanism:

```
id                     String(36), PK (UUID)
company_id             Integer, FK → companies.id, NOT NULL, index
notice_id              String(36), FK → notices.id, NOT NULL, index
is_relevant            Boolean, NOT NULL, default False
relevance_score        Float, nullable
classification_method  String(50), nullable
delivered_at           DateTime, nullable   -- set when included in a sent report
created_at             DateTime, NOT NULL, default now()

UNIQUE (company_id, notice_id)
```

A notice with no row here for a given company hasn't been classified/seen by that company yet — this absence *is* the delivery cursor. No separate cursor/checkpoint table needed.

### Modified tables

| Table | Change | Migration behaviour |
|---|---|---|
| `Notice` | **Unchanged schema.** `is_relevant`/`relevance_score`/`classification_method` become vestigial post-migration — no longer written by the pipeline (classification moves to `CompanyNoticeStatus`). Not dropped in this migration to avoid a breaking change; a follow-up cleanup migration can drop them once nothing reads them. | Historical values backfilled into `CompanyNoticeStatus` for the YULCOM company (see Migration section). |
| `Source` | **Unchanged.** Stays global per-country, YULCOM-managed. | — |
| `Run` | `run_type String(20) NOT NULL default 'harvest'` (`harvest` \| `delivery`); `company_id Integer FK → companies.id nullable` (null for harvest runs). | Existing rows backfilled as `run_type='harvest'`, `company_id=NULL`. |
| `Recipient` | `company_id Integer FK → companies.id nullable` (in addition to existing `country_id`). | Backfilled to the YULCOM company id. |
| `User` | `company_id Integer FK → companies.id nullable` (null only for `super_admin`). Role enum extended: `super_admin` \| `company_admin` \| `company_viewer` (renamed from `admin`/`viewer`). | Existing `admin`→`company_admin`, `viewer`→`company_viewer`, all backfilled to the YULCOM company id. |

---

## Section 2 — Pipeline

### Harvest graph (`agents/harvest_graph.py`, replaces the tail of today's `graph.py`)

```
load_sources → fetch_listings → extract_item_links → fetch_items → parse_extract → deduplicate
```

Ends after `deduplicate`. No `classify`, `summarize`, `compose_report`, `email_report` — those move to delivery. Cadence and trigger mechanism are unchanged from today (`TenderAIState.country_id`, `Run.run_type='harvest'`).

**Prerequisite fix (see Open Risks below):** `parse_extract.py`, `parse_pdf_structured.py`, and `parse_tavily_listing.py` currently set `classification_embedded=True` on items with relevance already judged (using YULCOM's fixed IT-scope criteria) *during extraction*, specifically so `classify_node` skips them. This must be neutralized — harvest-side parsing should produce structural extraction only (entity, reference, object, deadline, description, category), with no relevance judgment, so every company's delivery-side `classify` step sees the same unbiased raw notices.

### Delivery graph (`agents/delivery_graph.py`, new)

Triggered per company, iterates its enabled `CompanyCountrySubscription` rows. For each (company, country) pair:

```
select_new_notices → classify → summarize → compose_report → email_report → mark_delivered
```

- `select_new_notices`: `Notice` rows for this country with no `CompanyNoticeStatus` row for this company yet.
- `classify`: reads `CompanySettings["classification"]` instead of `CountrySettings["classification"]`; writes results to `CompanyNoticeStatus` (not `Notice`).
- `summarize`/`compose_report`/`email_report`: same node implementations as today, parameterized by `Company` branding + `Recipient` rows filtered by `company_id` + `country_id`.
- `mark_delivered`: sets `delivered_at` on the `CompanyNoticeStatus` rows included in the sent report.

`TenderAIState` gains `company_id: int` and `company_config: Dict[str, Any]` (mirroring `country_config`), plus a new `company_cfg()` accessor in `agents/_cfg.py` reading `state.company_config[section][key]`, backed by a new `CompanyStore` (mirrors `CountryStore.get_all_with_fallback`).

### Scheduler

Two job families now, both via the existing `get_scheduler_instance()`:

- **Harvest jobs** — unchanged, one per country (`reschedule_country_job`), cron from `CountrySettings["scheduler"]`.
- **Delivery jobs** — new, one per company (`reschedule_company_delivery_job`), cron from `CompanySettings["scheduler"]`, calls `scheduled_company_delivery_run(company_id)` which loops over that company's enabled subscriptions.

No ordering dependency between the two families: a delivery run querying `select_new_notices` before harvest finishes for the day just finds fewer new notices and catches them on its next scheduled run.

---

## Section 3 — Auth & API

### Roles

- `super_admin` — `company_id=NULL`. Only role that can create/manage `Company` rows and assign `company_admin` users to them.
- `company_admin` — `company_id` set. Full control within their company: subscriptions, `CompanySettings`, recipients, users of their own company.
- `company_viewer` — `company_id` set, read-only, optionally further restricted to one `country_id` within the company (mirrors today's `viewer` + `country_id`).

### Scoping

New `CompanyScopedUser` FastAPI dependency (mirrors the existing `SuperAdminUser`/`CurrentUser` pattern) injects the caller's `company_id` filter automatically; raises 403 if a `company_admin`/`company_viewer` targets another company's `company_id` by ID.

### New router: `api/routers/companies.py`

```
GET    /api/v1/admin/companies
POST   /api/v1/admin/companies                              — super_admin only
GET    /api/v1/admin/companies/{company_id}
PUT    /api/v1/admin/companies/{company_id}
DELETE /api/v1/admin/companies/{company_id}                 — soft-delete (active=False)

GET    /api/v1/admin/companies/{company_id}/countries        — subscribed countries (from shared catalog)
POST   /api/v1/admin/companies/{company_id}/countries        — subscribe (body: country_id)
DELETE /api/v1/admin/companies/{company_id}/countries/{id}   — unsubscribe (enabled=False)

GET    /api/v1/admin/companies/{company_id}/settings
GET    /api/v1/admin/companies/{company_id}/settings/{section}
PUT    /api/v1/admin/companies/{company_id}/settings/{section}
       — if section == "scheduler": calls reschedule_company_delivery_job()

POST   /api/v1/admin/companies/{company_id}/run              — manual delivery trigger
```

### Existing endpoints — `company_id` scoping added

| Endpoint | Change |
|---|---|
| `recipients.py` | Filtered by caller's `company_id` (super_admin: optional `?company_id=`) |
| `runs.py`, `reports.py` | `company_admin`/`viewer` see only `run_type='delivery'` rows for their own `company_id`. `super_admin` sees both harvest and delivery runs, all companies. |
| `sources.py` | Read-only for `company_admin`/`viewer`, scoped to their subscribed countries. Write endpoints stay `super_admin` only. |
| `users.py` | `company_id` required for `company_admin`/`company_viewer` roles (same pattern as today's `country_id` requirement). |

---

## Section 4 — Frontend

### `CompanyContext` (new, wraps `CountryContext`)

Mirrors `frontend/contexts/country-context.tsx` one level up:

- JWT gains `company_id` (nullable, null only for `super_admin`).
- `app/(dashboard)/layout.tsx` extracts `company_id` from the cookie the same way it already extracts `country_id`, passes `fixedCompanyId` to lock non-super_admin roles.
- `CompanyProvider` fetches `GET /api/v1/admin/companies` (super_admin: all; others: their own, locked); persists `selectedCompany` to `localStorage` for `super_admin` (mirrors `selectedCountryId`).
- **Key change to `CountryProvider`**: it now fetches only the *selected company's subscribed* countries (`GET /api/v1/admin/companies/{id}/countries`) instead of the full active-country catalog — so it must nest inside `CompanyProvider` and re-fetch when `selectedCompany` changes.

### Sidebar

New "Compagnies" nav item, `super_admin` only — company list, create/edit, assign `company_admin` users.

### Impacted pages

| Page | Change |
|---|---|
| Sources | Read-only for `company_admin`/`viewer`. New country-subscription checklist UI (likely under Settings). |
| Destinataires | Filtered by `selectedCompany` in addition to `selectedCountry`. |
| Paramètres | Classification keywords/thresholds, delivery cron, branding now read/write `CompanySettings` via the new `/companies/{id}/settings/{section}` endpoints. |
| Utilisateurs | Role labels become `company_admin`/`company_viewer`; creation form requires `company_id`. |
| Reports / Runs / Logs | Distinguish harvest runs (`super_admin` only) from delivery runs (company-scoped). |

### New proxy route

`app/api/proxy/companies/[...path]/route.ts` — mirrors the existing `countries` proxy pattern.

---

## Section 5 — Migration & Rollout

Single Alembic migration (or a short sequence):

1. Create `companies`, `company_country_subscriptions`, `company_settings`, `company_notice_status` tables.
2. Insert seed row: `Company(name="YULCOM Technologies", slug="yulcom", active=True)`.
3. Subscribe YULCOM to all currently-active countries (`CompanyCountrySubscription` for BF, CI, SN, CA, …).
4. Seed `CompanySettings["classification"]` and `["scheduler"]` for YULCOM from the current global `AppSettings`/`CountrySettings` values (per-country classification keywords are currently identical across countries per `settings.yaml`, so a single company-level section is a lossless carry-over).
5. Add `company_id` to `recipients`, `users`; backfill all existing rows to the YULCOM company id.
6. Add `run_type` (default `'harvest'`) and `company_id` (nullable) to `runs`.
7. Rename `User.role` values: `admin`→`company_admin`, `viewer`→`company_viewer` (`super_admin` unchanged).
8. Backfill `company_notice_status` from existing `Notice.is_relevant`/`relevance_score`/`classification_method` for every historical notice, tagged to the YULCOM company id — preserves history so existing reports/analytics keep working.
9. Register YULCOM's delivery scheduler job at the cadence its `CountrySettings["scheduler"]` sections used today (one delivery job initially, or one per subscribed country — see Open Risk below on cadence granularity).

---

## Out of Scope (this spec)

- Billing, usage quotas, subscription tiers.
- Self-serve company signup (super_admin-provisioned only).
- Per-company LLM provider/API keys (shared, YULCOM-managed).
- Per-company custom sources/portals outside the shared catalog.
- Per-(company × country) delivery cadence — one cron per company for now (see Open Risk).
- Merged multi-country digest reports (one report per company × country, matching today's shape).
- Subdomain/white-label routing (single app instance, row-level tenant scoping via login).
- Dropping the now-vestigial `Notice.is_relevant`/`relevance_score`/`classification_method` columns (kept for this migration, cleanup deferred).

---

## Open Risks / Points to Resolve During Implementation

1. **Harvest-side pre-classification must be neutralized.** `parse_extract.py:619`, `parse_pdf_structured.py:292`, and `parse_tavily_listing.py:289` all set `classification_embedded=True` with relevance already judged against YULCOM's fixed IT-scope criteria, and `classify_node` passes these through unchanged. This directly conflicts with per-company classification: a non-IT company subscribing to a country using these parsers would inherit YULCOM's IT-relevance judgment before ever seeing its own criteria applied. **First implementation task should be verifying the extent of this and converting these three parsers to structural-extraction-only** (drop relevance judgment from the extraction prompt/schema, keep entity/reference/object/deadline/description/category). This is a prerequisite, not a nice-to-have — without it, multi-company classification is only correct for IT-scoped companies.
2. **Delivery cadence granularity**: this spec assumes one cron per company (applied uniformly across all its subscribed countries). If a company needs different cadences per country, `CompanySettings["scheduler"]` would need to become keyed by country, and the delivery scheduler job model would need a third dimension. Confirmed out of scope for v1, flagged here in case it surfaces early.
3. **`docx_report.py`/`smtp_client.py` branding parameters** currently accept `country_name` as their primary label; need to verify they can cleanly take `company_name`/`Company` branding fields (logo, subject prefix, signature) without deeper rework — likely fine given they already take `country_name` as a plain string parameter, but worth confirming during implementation rather than assuming.
