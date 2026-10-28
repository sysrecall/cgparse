# Document Intelligence Platform

AI-powered ingestion, extraction, validation, and search of financial documents
(PDF · JPG · PNG · XLSX · XLS · CSV).

> Design and architecture decisions: see `../ARCHITECTURE.md` (kept outside the
> code repo together with the original assignment brief).

## Structure

```
packages/app-core/     shared library: models, schemas, clients, settings
services/api/          FastAPI service (upload, reads, corrections, search, SSE)
services/processing/   Celery workers (parse/OCR → LLM extraction → validate → index)
apps/web/              Next.js 14 UI (upload, progress, review, search)
seed/                  ground_truth.csv + sample documents (evaluation corpus)
scripts/               evaluate.py, seed.py
docs/                  db.md (DDL), api.md, prompts.md
```

## Status

🚧 Scaffold in progress — see build order in `../ARCHITECTURE.md` §16.

## Conventions

- **Commits:** semantic / conventional commits — `type(scope): summary`.
  Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`.
  Scopes match services: `api`, `processing`, `web`, `core` (app-core), `repo`.
