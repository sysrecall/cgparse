# Document Intelligence Platform

AI-powered ingestion, extraction, validation and search of financial documents
(PDF · JPG · PNG · XLSX · XLS · CSV).

Design decisions live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (kept outside
the code repo together with the original brief); the implemented system is
diagrammed in [`docs/architecture.md`](docs/architecture.md).

---

## What it does

1. **Upload** one or many files — magic-byte type sniffing, checksum dedupe, size limit.
2. **Process** each file through a Celery chain:
   `route → parse → extract → validate → index`.
   - `parse` — pdfplumber for digital PDFs, **OpenParser PaddleOCR-VL** for scans/images, pandas for CSV/XLSX. Writes per-page text + search chunks.
   - `extract` — **regex heuristics first** (deterministic, with match spans), then the **LLM** (NVIDIA NIM `nvidia/nemotron-3.5-bolt-e4b`) fills only what heuristics missed. Unknown values stay `null` with confidence `0.0` — never guessed.
   - `validate` — six rules: `missing_field`, `type_and_format`, `line_items_sum`, `subtotal_tax_total`, `negative_or_impossible_values`, `duplicate_invoice`. Any error → `needs_review`.
   - `index` — embeds every chunk into `text_chunks.embedding` (NVIDIA NIM `nvidia/nemotron-3.5-embed-1b`, requested at 1536 dims) so keyword and semantic search are both live; FTS itself is a generated column, so it needs no work here.
3. **Review & correct** — the UI lists documents, shows extracted fields, line items, validation findings and the stage timeline; human edits are stamped `confidence=1.0 / source="human"` and survive reprocessing.
4. **Search** — keyword full-text across chunk text + filename, or hybrid semantic search (`?semantic=true`) that fuses pgvector similarity with keyword rank via reciprocal rank fusion. Results are grouped one entry per document with the best snippets, and every filter applies to both modes.

## Architecture

[`docs/architecture.md`](docs/architecture.md) contains:

- the **system diagram** — web, API, workers, Tigris, Postgres, Redis, and the
  two hosted AI providers, with the exact task names and queues;
- the **upload** and **pipeline** sequence diagrams, including failure and
  idempotency behaviour;
- the **document state machine** (`queued → processing → validated |
  needs_review | failed`, plus correction/reprocess edges);
- the **ER diagram** and a column-by-column **schema reference** for all nine
  tables, their `CHECK` constraints, indexes and the `JSONB` payload shapes.

## Structure

```
packages/app-core/     shared library: models, schemas, clients, settings, migrations
services/api/          FastAPI: upload, reads, corrections, reprocess, search
services/processing/   Celery workers: parse/OCR → LLM extraction → validate → index
apps/web/              Next.js 16 UI (upload, progress, review, search)
seed/                  sample + labeled evaluation corpora
scripts/               make_samples.py, make_eval_dataset.py, evaluate.py
docs/                  architecture + schema diagrams, evaluation report, metrics, test results, AI disclosure
```

`app-core` is the contract both services share; the API **never** imports worker
code (it only enqueues pipeline entry tasks), and the workers never start a web
server.

---

## Prerequisites

- **Python 3.12** with [uv](https://docs.astral.sh/uv/)
- **Node 20+** with [pnpm](https://pnpm.io/) 11
- **Supabase** Postgres with the `pgvector` extension (connection **pooled**, port 6543)
- **Upstash** Redis
- **Tigris** bucket (S3-compatible)
- **OpenParser** API key (OCR) and an **NVIDIA NIM** API key (LLM)

No Docker: every piece is a plain local process or a hosted free tier.

## Configuration

Copy `.env.example` to `.env` and fill it in. The variable groups:

| Group | Prefix | Used by |
|---|---|---|
| Shared | `DATABASE_URL`, `REDIS_URL`, `TIGRIS_BUCKET`, `AWS_*` | api **and** processing |
| API | `API_*` | services/api |
| Processing | `PROC_*` (falls back to `OPENPARSER_API_KEY` / `LLM_API_KEY`) | services/processing |
| Embeddings | `EMBED_*` (falls back to `PROC_LLM_API_KEY` / `LLM_BASE_URL`) | api **and** processing |

Integration tests and the evaluation harness need an **extra, dedicated Supabase
dev project** via `TEST_DATABASE_URL`. It is aliased to `DATABASE_URL` inside the
test process, and the DB-marked tests truncate every table before each test — so
**never** point it at a database you care about.

The web app does not read the repo-root `.env`; it has its own
`apps/web/.env.local`, which only needs `NEXT_PUBLIC_API_URL` when the API is not
on `http://localhost:8000`.

## Install

```bash
# Python services (each is its own project; uv manages per-project venvs)
cd services/api            && uv sync
cd ../processing           && uv sync
cd ../../packages/app-core && uv sync

# Web
cd ../../apps/web && pnpm install
```

## Database migrations

```bash
cd packages/app-core
set -a && source ../../.env && set +a
uv run alembic upgrade head
```

Creates 9 tables, the `vector` extension, the FTS generated column and the HNSW index.

## Run

```bash
# API
cd services/api && set -a && source ../../.env && set +a
uv run uvicorn app.main:app --reload --port 8000

# Worker (two queues; --concurrency 2 is a good default for long LLM tasks)
cd services/processing && set -a && source ../../.env && set +a
uv run celery -A app.celery_app:celery_app worker -Q ocr,llm --loglevel=info --concurrency=2

# Web
cd apps/web && pnpm dev
```

- UI: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>

Set `NEXT_PUBLIC_API_URL` in `apps/web/.env.local` if the API is not on
`http://localhost:8000`.

## Live deployment

A working instance runs on free tiers:

- **Web UI** — <https://cgparse.vercel.app>
- **API** — <https://cgparse.onrender.com> (docs at `/docs`, health at `/health`)

The free API instance sleeps when idle, so the first request after a pause can
take ~30 s to wake.

---

## Tests

Each project owns its suite. DB-marked tests auto-skip unless `TEST_DATABASE_URL`
is set; unit tests always run.

```bash
cd packages/app-core     && uv run pytest      # schemas, DB-URL normalization
cd services/processing   && uv run pytest      # parsers, extraction, validation, pipeline
cd services/api          && uv run pytest      # ingest, upload, reads, corrections, search
```

| Suite | Coverage |
|---|---|
| app-core | Extraction contract (anti-hallucination), money/date coercion, URL normalization |
| processing — unit | CSV/XLSX quirks, digital vs scanned PDF routing, heuristics vs LLM merge, all six validation rules |
| processing — `@pytest.mark.db` | Pipeline stages against the dev DB: idempotency, human-edit preservation, failure marking, chain dispatch |
| api — unit | Magic-byte sniffing, filename safety, size/empty limits, embedding failure surfacing, query validation |
| api — `@pytest.mark.db` | Upload→202 per-file isolation + dedupe, list/filter/pagination, detail & pages, corrections, reprocess, search (FTS/grouping/filters) |

Providers are replaced in tests: Tigris uploads are captured in a dict, queue
enqueues recorded, Redis pub/sub swapped for a list. The LLM is monkeypatched in
unit tests; real-LLM integration is opt-in.

Run the whole thing (with the dev DB exported):

```bash
for p in packages/app-core services/processing services/api; do (cd $p && uv run pytest); done
```

Latest recorded results — counts, durations, environment, lint and web build —
are in [`docs/test_results.md`](docs/test_results.md).

### Lint

```bash
(cd services/api && uv run ruff check .)
(cd services/processing && uv run ruff check .)
(cd packages/app-core && uv run ruff check .)
uv run --project services/processing ruff check scripts
```

---

## Evaluation harness

`scripts/evaluate.py` runs the **real** pipeline (real parsers, real OCR, real
LLM, real rule engine) over the labeled corpus in `seed/eval/`, against the
dedicated dev database, with object storage and Redis replaced by in-memory
equivalents. It reports field accuracy, null/hallucination detection, line-item
accuracy, validation precision/recall/F1, per-stage latency, success/review/failure
rates and LLM token usage.

```bash
# (re)generate the corpus (deterministic; ~31 docs incl. edge cases)
uv run --project services/processing python scripts/make_eval_dataset.py

# run the evaluation (needs TEST_DATABASE_URL)
uv run --project services/processing python scripts/evaluate.py --workers 4

# quick smoke without the LLM
uv run --project services/processing python scripts/evaluate.py --limit 5 --no-llm
```

Outputs:

- `docs/metrics_report.md` — human-readable report
- `docs/metrics.json` — chart-ready raw metrics + per-document results

The corpus deliberately includes: clean invoices across all input types,
thousands-separated money, missing tax/currency/customer, a non-ISO (US) date, a
long-form date, no line items, a line-items-vs-subtotal mismatch, an arithmetic
mismatch, a duplicate pair, multi-page PDFs, and empty-file parse failures.
Reruns only touch documents whose filename starts with `eval_` — the harness
deletes and re-inserts exactly those rows.

## Data & schema

- UUID v4 primary keys, generated DB-side.
- Statuses/kinds are plain strings validated by `StrEnum` + `CHECK` constraints.
- Money is `NUMERIC(12,2)`; line-item `CHECK`s forbid negative values.
- `text_chunks.content_tsv` is a generated `tsvector` column; `embedding` is a
  `vector(1536)` written by the pipeline's `index` stage (HNSW cosine index).

## AI usage

[`docs/ai_usage.md`](docs/ai_usage.md) discloses both sides of AI in this project:
the AI coding agent used to build it (with how its output was verified) and the
runtime models — OpenParser `paddleocr-vl-1.6` for OCR and NVIDIA NIM
`nvidia/nemotron-3.5-bolt-e4b` for extraction — including the verbatim prompts, the
anti-hallucination guardrails and the measured results.

## Known limitations (v1)

- Semantic search needs an embedding key: without `EMBED_API_KEY` (or the shared
  NVIDIA key) `?semantic=true` returns `503`; documents indexed before embeddings
  existed have no vectors until reprocessed.
- TIFF is out of scope.
- Negative line-item values can't be persisted (DB `CHECK`), so that rule is only
  exercised by unit tests.
- Heuristic dates are literal evidence — a non-ISO date is kept verbatim and
  flagged by `type_and_format` instead of auto-converted.
