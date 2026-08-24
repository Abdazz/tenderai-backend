# TenderAI BF — Backend

API, pipeline LangGraph, IA et traitements asynchrones du harvester d'appels d'offres TenderAI BF.

Fait partie de l'architecture à 3 repos :
- [`tenderai-frontend`](https://github.com/abdazz/tenderai-frontend) — interface Next.js
- [`tenderai-infra`](https://github.com/abdazz/tenderai-infra) — Docker, CI/CD, déploiement

## Démarrage rapide

```bash
cp .env.example .env
# Copier settings.yaml depuis tenderai-infra vers la racine de ce repo
make install-dev
make up-deps
make migrate
make run-once
```

Voir `CLAUDE.md` pour le détail des commandes disponibles.
