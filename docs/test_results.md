# Test results

Measured on **2026-11-01** against `main` at `c76b260` (code identical to
`99049ee`; only documentation changed afterwards).

- **Python** 3.12.3 (local) · **uv** per-project environments
- **Node** 22.22.3 · **pnpm** 11.5.0
- **Database** the dedicated Supabase dev project from `TEST_DATABASE_URL`
  (every DB-marked test truncates its tables, so this is never a shared project)

Commands below are run from the repository root with `set -a && . ./.env && set +a`
so the DB tests are not skipped.

## 1. Summary

| Suite | Tests | Result | Duration |
|---|---|---|---|
| `packages/app-core` | 44 | passed | 2.1 s |
| `services/processing` | 77 | passed | 124 s |
| `services/api` | 68 | passed | 296 s |
| **Total** | **189** | **189 passed, 0 failed, 0 skipped** | ~7 min |

Durations are dominated by real network round-trips to the dev database; they
move with connection latency and are not a performance claim.

The processing and API suites each emit **one third-party deprecation warning**
(`fitz` → `pymupdf`, Starlette `TestClient` + `httpx`). Neither comes from this
codebase and neither affects a result.

```bash
for p in packages/app-core services/processing services/api; do
  (cd "$p" && uv run pytest -q)
done
```

DB-marked tests skip automatically when `TEST_DATABASE_URL` is unset; the counts
above include them.

## 2. What the tests cover

| Area | Representative tests |
|---|---|
| Extraction contract | absent fields stay `null`/`0.0`, money and dates are coerced, LLM money not present in the source is discarded, heuristic values win over the LLM |
| Parsers | CSV quoting/ragged rows, XLSX empty cells and multi-line cells, digital-vs-scanned PDF routing, OCR page normalization (including tables rebuilt from cells/HTML) |
| Validation | all six rules, severity → `validated` / `needs_review` routing |
| Pipeline (DB) | stage idempotency, failure marking, human-edit preservation, chain dispatch |
| Ingest (DB) | magic-byte sniffing, size/empty limits, per-file 202 isolation, checksum dedupe, duplicate rollback |
| API (DB) | list/filter/pagination, detail and pages, corrections, reprocess, FTS + hybrid search, grouping, CORS origin normalization |
| Embeddings | request shape (model, dimensions, input type), provider failure → 503, `semantic=false` never calls the provider |

Providers are replaced in unit tests (storage dict, recorded enqueues, list-backed
pub/sub, monkeypatched LLM); the DB tests use the real schema. Real-provider
behaviour is measured separately by the evaluation harness.

## 3. Lint and build

| Check | Command | Result |
|---|---|---|
| Python lint | `uv run ruff check .` in each project | clean (3 projects) |
| Scripts lint | `uv run --project services/processing ruff check scripts` | clean |
| Web lint | `pnpm lint` in `apps/web` | clean |
| Web build | `pnpm build` in `apps/web` | compiled, TypeScript clean, all 6 routes generated |

The web app has **no unit-test suite**; it is covered by ESLint, a production
build and the live smoke checks in the walkthrough. That is a deliberate scope
choice for v1, not an oversight — the server-side behaviour it depends on is
tested in `services/api`.

## 4. Evaluation (real providers)

The harness is separate from pytest because it calls the real OCR and LLM
providers and needs the corpus in the database:

```bash
uv run --project services/processing python scripts/evaluate.py --workers 4
```

Latest run (31 documents): **24 validated · 5 needs_review · 2 failed**,
expected-status accuracy **1.0000**, macro field accuracy **0.9957**,
line-item precision/recall **1.0000**, validation F1 **1.0000**, wall time
**185 s**. Full tables, per-document results and raw numbers:
[`metrics_report.md`](metrics_report.md) and [`metrics.json`](metrics.json).
