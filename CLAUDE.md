# CLAUDE.md

Backend de TenderAI — API FastAPI, pipeline LangGraph (`agents/graph.py`), classification IA, génération de rapports DOCX, livraison email.

Ce repo fait partie d'une architecture à 3 repos : `tenderai-backend` (ce repo), `tenderai-frontend`, `tenderai-infra`. `tenderai-infra` est la racine — ce repo et `tenderai-frontend` vivent comme sous-dossiers gitignorés à l'intérieur. Le développement local de ce repo est autonome (`make setup` démarre postgres/minio/api/worker). Pour un test d'intégration full-stack avec le frontend, voir `tenderai-infra`.

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

Le pipeline LangGraph est scindé en deux graphes qui partagent un même `TenderAIState` (défini dans `agents/graph.py`) :

- **Graphe harvest** (`TenderAIGraph`, `agents/graph.py`, par pays) : `load_sources → fetch_listings → extract_item_links → fetch_items → parse_extract → deduplicate → persist_notices`. Persiste uniquement des `Notice` structurelles, sans jugement de pertinence.
- **Graphe delivery** (`DeliveryGraph`, `agents/delivery_graph.py`, par entreprise, itère les pays auxquels elle est abonnée) : `select_new_notices → classify → summarize → compose_report → email_report → mark_delivered`. `select_new_notices` lit les `Notice` sans ligne `CompanyNoticeStatus` pour cette entreprise — cette absence est le curseur de livraison. `classify` est le seul endroit où la pertinence est décidée, par entreprise, et écrit la ligne `CompanyNoticeStatus` qui devient ce curseur.

`get_pipeline()` (harvest) et `get_delivery_pipeline()` (delivery) sont deux singletons thread-safe indépendants.

## Config locale

`settings.yaml` (racine de ce repo, non versionné ici — copié depuis `tenderai-infra`) et `.env` (copié depuis `.env.example`) sont requis pour `make up`.
