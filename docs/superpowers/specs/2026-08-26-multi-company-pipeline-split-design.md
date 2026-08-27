# Multi-Company Pipeline Split — Design Spec (Plan #2)

**Date:** 2026-08-26
**Status:** Approved (pending final spec review)
**Refs:** `docs/superpowers/specs/2026-08-23-multi-company-design.md` (Section 2 — Pipeline, Section 5 — Open Risk #1, which this spec implements); `docs/superpowers/plans/2026-08-23-multi-company-data-model.md` (Plan #1, prerequisite, fully merged)

---

## Context

Plan #1 (data model) is complete and merged: `Company`, `CompanyCountrySubscription`, `CompanySettings`, `CompanyNoticeStatus` tables exist; `Run.run_type`/`company_id`, `Recipient.company_id`, `User.company_id` + role rename are live; `CompanyStore` mirrors `CountryStore`; YULCOM is seeded as company zero. None of it is wired into the pipeline yet — `agents/graph.py` still runs one undifferentiated pipeline per country, with no notion of `Company` anywhere in `agents/`.

This plan (chantier 3, "Plan #2" in the original spec's own numbering) implements the multi-company design's Section 2 (Pipeline) and closes its Open Risk #1 (harvest-side pre-classification), which the original spec calls a hard prerequisite: *"without it, multi-company classification is only correct for IT-scoped companies."*

**A load-bearing discovery made during this plan's design, not anticipated by the original spec:** the current pipeline never persists `Notice` rows to the database at all. Everything flows in-memory through `TenderAIState` (`items_raw` → `items_parsed` → `unique_items`), gets built into a report, gets emailed, and is discarded — only the `Run` row and the generated `.docx` (in MinIO) survive. `deduplicate_node`'s hash comparison is scoped to the current run's in-memory batch only, never against history. The original spec's delivery-graph design (`select_new_notices`: *"Notice rows for this country with no CompanyNoticeStatus row"*) assumes `Notice` persistence as a given; it doesn't exist today. This plan introduces it as new, in-scope work.

---

## Scope Decisions (confirmed during brainstorming)

1. **Notice persistence is new scope for this plan**, not deferred to a separate plan — verified via `git grep` against `main` that no node constructs or commits a `Notice` row anywhere in the current pipeline.
2. **Deduplication stays run-scoped only** — no check against already-persisted `Notice` history at harvest time. The same tender can be re-harvested and re-persisted as a new `Notice` row (fresh UUID) across two separate runs.
3. **Consequence of (2), explicitly accepted:** a company can receive the same tender in two different daily delivery reports (once per re-harvest event, since each `Notice` id is new and `CompanyNoticeStatus` sees it as unprocessed). Not solved by this plan; upsert-by-`content_hash` was considered and explicitly rejected in favor of simplicity for now.
4. **`run-once` CLI takes `--country` and `--company` (by code/slug, not numeric id) together, required.** A single invocation runs harvest for that country immediately followed by delivery for that company, scoped to that one country only (not the company's full subscription list). No standalone harvest-only invocation via this command going forward.
5. **Production scheduled jobs stay fully decoupled**, matching the original spec: one cron family per country (harvest, unchanged), one cron family per company (delivery, new). No ordering dependency; `run-once`'s combined behavior is a manual/testing convenience only, not how production scheduling works.
6. **Shared `TenderAIState`, not split state classes.** `TenderAIState` gains `company_id`/`company_config`; harvest and delivery each build their own `StateGraph(TenderAIState)` but share the same Pydantic model, `error_handler`, and `_route_after_step` machinery. Rejected: two separate state classes (cleaner boundaries, but touches every existing node's type hints for no behavioral gain at this stage).

---

## Section 1 — Harvest-side changes

### Neutralize `classification_embedded`

`parse_extract.py`, `parse_pdf_structured.py`, `parse_tavily_listing.py` currently have their extraction LLM prompts judge relevance against YULCOM's fixed IT-scope criteria and set `classification_embedded=True` on the resulting items. Trim these three prompts/schemas to structural fields only: `title`, `reference`, `entity`, `category`, `deadline`, `description`, `document_url` — no relevance judgment, no `is_relevant`/`relevance_score` in the output.

`classify.py`'s 4 call sites that branch on `item.get("classification_embedded")` (the "pass through directly" quality-gate logic) are deleted. Every item now goes through the same keyword/LLM classification path uniformly — `classify_node` becomes the single place relevance is decided.

### New step: `persist_notices`

Added to the harvest graph immediately after `deduplicate`. For each item surviving in-run dedup:
- Resolve `item["source_name"]` → `Source.id` (lookup by name + `country_id`; items don't currently carry a numeric `source_id`).
- Insert a `Notice` row: `NoticeBase` structural fields (`title`, `ref_no`, `entity`, `category`, `published_at`, `deadline_at`, `location`, `budget_xof`, `currency`, `description`, `url`) + `source_id`, `run_id`, `content_hash`.
- `is_relevant`/`relevance_score`/`classification_method` are **never written by harvest** — left at column defaults. They are formally vestigial from this point forward, exactly as the original spec anticipated, except now enforced by construction (harvest has no relevance information to write) rather than merely by convention.

### Harvest graph

`load_sources → fetch_listings → extract_item_links → fetch_items → parse_extract → deduplicate → persist_notices`. Ends there. No `classify`, `summarize`, `compose_report`, `email_report` — those move entirely to delivery.

---

## Section 2 — Delivery graph (new)

New file `agents/delivery_graph.py`, its own `DeliveryGraph` class following the same `_AppWrapper`/`_route_after_step`/`error_handler` pattern as today's `TenderAIGraph`.

**`select_new_notices`** — for the (company, country) pair being processed:
```sql
Notice JOIN Source ON Notice.source_id = Source.id
WHERE Source.country_id = :country_id
  AND NOT EXISTS (
    SELECT 1 FROM company_notice_status
    WHERE company_id = :company_id AND notice_id = notices.id
  )
```
Converts matching rows into the same dict shape `classify_node` already consumes (`title`, `entity`, `description`, `location`, `reference`, `deadline`, `id`, …), populates `state.items_parsed`.

**`classify`** — reused matching logic (keyword/LLM), delivery-only now (harvest no longer includes this node, so no dual-mode branching needed). Two changes from today: reads `company_cfg(state, "classification", ...)` instead of `cfg(state, "pipeline"/"classification", ...)`; and, matching the original spec's own wording ("writes results to `CompanyNoticeStatus`"), **writes a `CompanyNoticeStatus` row for every classified item immediately** — relevant or not, `delivered_at=NULL`. This is required: a `CompanyNoticeStatus` row's *absence* is the delivery cursor, so an irrelevant notice still needs a row recorded or it gets reclassified on every future delivery run. Upsert on `(company_id, notice_id)`.

**`summarize` / `compose_report` / `email_report`** — same node implementations, now driven by `Company` branding (`logo_url`, `subject_prefix`, `signature`) instead of the current `country_name`-only parameter. `email_report`'s `Recipient` query gains `Recipient.company_id == state.company_id` alongside the existing `Recipient.country_id` filter.

**`mark_delivered`** — new, final node: sets `delivered_at = now()` on the `CompanyNoticeStatus` rows for whichever items actually made it into the sent report.

Delivery graph: `select_new_notices → classify → summarize → compose_report → email_report → mark_delivered`.

### `TenderAIState` / `_cfg.py` changes

- `TenderAIState` gains `company_id: int = 0` and `company_config: dict[str, Any] = Field(default_factory=dict)`.
- New `company_cfg(state, section, key)` in `agents/_cfg.py`, mirroring `cfg()` exactly (same fail-hard `RuntimeError` on missing key), backed by `CompanyStore.get_all_with_fallback`.

---

## Section 3 — Entry points & scheduler

### CLI (`cli.py run-once`)

Extends the existing `--country-id`/`--country-code` pair with a new `--company-id`/`--company-code` pair, resolved the same way (`--company-code` looked up against `Company.slug` via the existing raw-SQL-lookup pattern used for country). Both country and company become **required** — no standalone harvest-only invocation through this command. Behavior: `HarvestGraph().run(country_id=...)`, then immediately `DeliveryGraph().run(company_id=..., country_id=...)`, scoped to just that one country (not the company's full subscription list — that behavior belongs to the scheduled delivery job below). `--test` flag continues to control admin-only email as today.

`run-once` does **not** check `CompanyCountrySubscription` before running delivery — it's a manual testing/ops tool, and enforcing "is this company actually subscribed to this country" would get in the way of ad-hoc verification (e.g. testing delivery for a country before formally subscribing a company to it). Subscription enforcement belongs to the scheduled delivery job below, which only ever iterates a company's *enabled* subscriptions in the first place.

### Scheduler — two independent job families, no ordering dependency

- **Harvest** (existing, unchanged behavior, rewired implementation): `reschedule_country_job` / `scheduled_pipeline_run(country_id)`, now calling `HarvestGraph().run(country_id=...)` instead of today's single `TenderAIGraph`.
- **Delivery** (new): `reschedule_company_delivery_job(company_id, company_slug, scheduler_cfg)`, mirroring the harvest version (`job_id=f"delivery_{company_slug}"`, cron from `CompanySettings["scheduler"]`). Calls `scheduled_company_delivery_run(company_id)`, which loops the company's enabled `CompanyCountrySubscription` rows and runs `DeliveryGraph().run(company_id=..., country_id=sub.country_id)` for each subscribed country — this is the only path where a company's delivery actually spans all of its subscriptions.

No API/UI exists yet to configure delivery cron (Section 3 of the original spec — Auth & API — is a later plan). `CompanySettings["scheduler"]` is set via direct DB/CLI for now, the same bootstrapping gap country-level scheduling had before its own settings API existed.

---

## Section 4 — Testing & rollout

**New tests:** `tests/nodes/test_persist_notices.py`, `tests/nodes/test_select_new_notices.py`, `tests/nodes/test_mark_delivered.py`. `test_classify.py` updated for delivery-only operation (`company_cfg` instead of `cfg`, asserting `CompanyNoticeStatus` writes instead of item-dict mutation as the primary output). Existing `parse_extract`/`parse_pdf_structured`/`parse_tavily_listing` tests likely assert on the now-removed `classification_embedded`/`is_relevant` output fields and need updating to match structural-only extraction.

**No data migration needed** — Plan #1 already backfilled `CompanyNoticeStatus` from historical `Notice.is_relevant` for YULCOM.

**Rollout:** YULCOM's daily cadence continues via `run-once --country=BF --company=yulcom` (manual/testing) or two independently-scheduled crons (harvest at its existing cadence, delivery on a new cron set to roughly the same time) — no forced simultaneity, consistent with the "occasional duplicate across days is acceptable" decision above. First manual verification: run harvest for BF, confirm `Notice` rows land with `is_relevant` NULL/default; run delivery for `yulcom` + BF, confirm `CompanyNoticeStatus` rows appear and the email still sends correctly.

---

## Out of Scope (this plan)

- Everything in the original spec's Section 3 (Auth & API) and Section 4 (Frontend) — no `companies` API router, no company-scoping on existing endpoints, no `CompanyContext`/company UI. This plan only touches `agents/`, `scheduler/`, and `cli.py`.
- Upsert-by-`content_hash` / cross-run dedup at harvest time (explicitly rejected above).
- Per-(company × country) delivery cadence — one cron per company, matching the original spec's v1 scope.
- Dropping `Notice.is_relevant`/`relevance_score`/`classification_method` columns (kept vestigial, per original spec).
- Any change to `deduplicate_node`'s in-run comparison logic itself — only the new `persist_notices` step is added after it.

## Open Risks / Points to Resolve During Implementation

1. **`source_name` → `Source.id` resolution at persist time** — items carry a string `source_name`, not a numeric `source_id`. The lookup (by name + `country_id`) needs to handle the case where no matching `Source` row exists (e.g. a renamed or since-disabled source) — decide whether this is a hard failure for that item or a skip-with-warning during implementation.
2. **`CompanyNoticeStatus` upsert semantics** — confirm the exact upsert mechanism (SQLAlchemy `merge()`, matching `CompanyStore.put_section`'s existing pattern, vs. an explicit `SELECT ... FOR UPDATE` + insert-or-update) during implementation; a delivery run should never fail outright just because a notice was already classified by a concurrent/retried run.
3. **`select_new_notices` query performance** — the `NOT EXISTS` anti-join runs once per (company, country) delivery cycle; verify it performs acceptably once `notices`/`company_notice_status` accumulate real volume (both already have relevant indexes per Plan #1 and the existing `Notice` model — worth a quick `EXPLAIN` check during implementation, not blocking design).
