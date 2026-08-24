# CLAUDE.md

Backend de TenderAI BF — API FastAPI, pipeline LangGraph (`agents/graph.py`), classification IA, génération de rapports DOCX, livraison email.

Ce repo fait partie d'une architecture à 3 repos : `tenderai-backend` (ce repo), `tenderai-frontend`, `tenderai-infra`. Le développement local de ce repo est autonome (`make setup` démarre postgres/minio/api/worker). Pour un test d'intégration full-stack avec le frontend, voir `tenderai-infra`.

## Commands

```bash
make install-dev      # deps + dev tools
make dev               # format + lint + test
make up-deps            # postgres, minio, createbuckets
make migrate             # alembic upgrade head
make run-once             # exécute le pipeline une fois
make test                  # pytest tests/ -v
```

## Architecture

Voir le pipeline LangGraph dans `src/tenderai_bf/agents/graph.py` : `load_sources → fetch_listings → extract_item_links → fetch_items → parse_extract → classify → deduplicate → summarize → compose_report → email_report`.

## Config locale

`settings.yaml` (racine de ce repo, non versionné ici — copié depuis `tenderai-infra`) et `.env` (copié depuis `.env.example`) sont requis pour `make up`.
