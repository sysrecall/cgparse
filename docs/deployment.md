# Deployment

Target: **Render** for the two Python services, **Vercel** for the web app.
This is a personal deployment, not a production topology — no Docker, no custom
domains, no autoscaling.

```
Vercel (Next.js)  ──HTTPS──▶  Render web service (FastAPI)  ──┐
                                   │  send_task              │
                                   ▼                         │
                              Upstash Redis  ◀───────────────┤
                                   │  ocr / llm              │
                                   ▼                         │
                              Render worker (Celery) ────────┤
                                                             │
   Supabase Postgres (pgvector) ◀────────────────────────────┘
   Tigris S3 (careguide bucket)
```

## Why both services build from the repo root

`services/api` and `services/processing` are standalone uv projects whose
`uv.lock` resolves `app-core` through the relative path
`../../packages/app-core`. A Render *root directory* of `services/api` would put
`packages/` outside the build context and the sync would fail. So the services
declare no root directory, and the build/start commands `cd` themselves:

```bash
pip install uv && uv sync --frozen --no-dev --project services/<service>
cd services/<service> && uv run --no-sync <command>
```

`pip install uv` comes first because Render only provisions uv automatically when
a `uv.lock` sits in the service root — here the lockfiles are one level down.
`--no-sync` keeps `uv run` from re-resolving at start time (the build already
synced, and `uv run` would otherwise reinstall the dev group).

## Prerequisites

```bash
# Render CLI
curl -fsSL https://raw.githubusercontent.com/render-oss/cli/refs/heads/main/bin/install.sh | sh
render login          # or: export RENDER_API_KEY=rnd_...

# Vercel CLI
pnpm add -g vercel@latest
vercel login
```

The repo must be reachable by Render (GitHub/GitLab/Bitbucket):

```bash
cd repo
gh repo create careguide --private --source=. --push
```

## 1. Migrations

Migrations need the Supabase **session pooler (port 5432)** and a role allowed to
`CREATE EXTENSION vector`. Run them once from the laptop before the first deploy;
`render.yaml` also runs the same command as the worker's `preDeployCommand` (free
web services cannot run pre-deploy commands, paid workers can).

```bash
cd packages/app-core
set -a && source ../../.env && set +a
export DATABASE_URL="postgresql+psycopg://<user>:<pass>@<host>:5432/<db>"
uv run alembic upgrade head
uv run alembic current
```

## 2. Render

### Blueprint (recommended)

`render.yaml` at the repo root defines both services plus a shared env group.
Secrets use `sync: false`, so Render prompts for them at creation time and never
reads them from git. `sync: false` is not allowed inside an env group, which is
why only non-secret values live in `careguide-shared`.

```bash
render blueprint validate
render blueprint launch          # creates both services, prompts for the secrets
```

Values to have ready for the prompts: `DATABASE_URL`, `REDIS_URL`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `PROC_OPENPARSER_API_KEY`,
`PROC_LLM_API_KEY`.

### Equivalent CLI commands

```bash
render services create \
  --name careguide-api \
  --type web_service \
  --repo https://github.com/<you>/careguide \
  --branch main \
  --runtime python \
  --plan free \
  --build-command 'pip install uv && uv sync --frozen --no-dev --project services/api' \
  --start-command 'cd services/api && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT' \
  --health-check-path /health \
  --env-var 'PYTHON_VERSION=3.12.11' \
  --env-var 'PYTHONPATH=/opt/render/project/src/services/api' \
  --env-var 'DATABASE_URL=postgresql+psycopg://...' \
  --env-var 'REDIS_URL=rediss://...' \
  --env-var 'AWS_ACCESS_KEY_ID=...' \
  --env-var 'AWS_SECRET_ACCESS_KEY=...' \
  --env-var 'AWS_ENDPOINT_URL_S3=https://t3.storage.dev' \
  --env-var 'AWS_REGION=auto' \
  --env-var 'TIGRIS_BUCKET=careguide' \
  --env-var 'API_CORS_ORIGINS=http://localhost:3000' \
  --env-var 'API_MAX_UPLOAD_MB=200' \
  --output json

render services create \
  --name careguide-worker \
  --type background_worker \
  --repo https://github.com/<you>/careguide \
  --branch main \
  --runtime python \
  --plan 0.5c-512mb \
  --build-command 'pip install uv && uv sync --frozen --no-dev --project services/processing' \
  --start-command 'cd services/processing && uv run --no-sync celery -A app.celery_app:celery_app worker -Q ocr,llm --concurrency=2 --loglevel=info' \
  --max-shutdown-delay 300 \
  --pre-deploy-command 'cd packages/app-core && uv run --no-sync alembic upgrade head' \
  --env-var 'PYTHON_VERSION=3.12.11' \
  --env-var 'PYTHONPATH=/opt/render/project/src/services/processing' \
  --env-var 'DATABASE_URL=postgresql+psycopg://...' \
  --env-var 'REDIS_URL=rediss://...' \
  --env-var 'AWS_ACCESS_KEY_ID=...' \
  --env-var 'AWS_SECRET_ACCESS_KEY=...' \
  --env-var 'AWS_ENDPOINT_URL_S3=https://t3.storage.dev' \
  --env-var 'AWS_REGION=auto' \
  --env-var 'TIGRIS_BUCKET=careguide' \
  --env-var 'PROC_OPENPARSER_API_KEY=...' \
  --env-var 'PROC_LLM_API_KEY=...' \
  --env-var 'PROC_LLM_BASE_URL=https://integrate.api.nvidia.com/v1' \
  --env-var 'PROC_LLM_MODEL=openai/gpt-oss-20b' \
  --output json
```

Notes:

- `background_worker` is the CLI's name for the type the dashboard and Blueprint
  call `worker`.
- `PYTHON_VERSION` must be fully qualified (`3.12.11`, not `3.12`) when set as an
  environment variable.
- `maxShutdownDelaySeconds: 300` / `--max-shutdown-delay 300` lets in-flight OCR
  and LLM tasks finish on redeploy. It pairs with `task_acks_late=True`: an
  interrupted task is redelivered rather than lost.
- One worker consumes both `ocr` and `llm`. Split them into two services only if
  LLM stages should not queue behind a slow OCR batch.
- The free web plan sleeps after 15 minutes idle; the next request takes roughly
  a minute to wake. The worker has no free plan.

## 3. Vercel

`NEXT_PUBLIC_*` variables are inlined at build time, so they must exist before the
build runs.

```bash
cd apps/web
vercel link --yes --project careguide-web

vercel env add NEXT_PUBLIC_API_URL production    # https://careguide-api.onrender.com
vercel env add NEXT_PUBLIC_API_URL preview       # same URL
vercel env add NEXT_PUBLIC_API_URL development   # http://localhost:8000

vercel --prod
```

In the dashboard set **Root Directory** to `apps/web` so git-push auto-deploys
build the same project the CLI builds. Node 22.x if the build complains.

## 4. CORS second pass

`API_CORS_ORIGINS` is an exact-match allowlist, and the Vercel domain is only
known after the first deploy:

```bash
render services update careguide-api \
  --env-var 'API_CORS_ORIGINS=https://careguide-web.vercel.app,http://localhost:3000'
```

Preview deployments get a per-deploy `<project>-<hash>-<team>.vercel.app` origin
and will fail CORS unless that exact origin is added. Simplest workaround: preview
against a locally running API.

## 5. Verify

```bash
API=https://careguide-api.onrender.com

curl -s $API/health                                   # {"status":"ok"}
curl -s -F 'file=@invoice.pdf' $API/documents | jq    # id + status "queued"
render logs --service careguide-worker --tail         # route → parse → extract → validate → index
curl -s "$API/documents/<id>" | jq .status            # validated | needs_review
curl -s "$API/search?q=acme" | jq '.results | length'
curl -s "$API/search?q=acme&semantic=true" -o /dev/null -w '%{http_code}\n'   # 501
```

Then walk the five web pages against those documents.

## Gotchas

- **libmagic.** `services/api` calls `magic.from_buffer` to sniff uploads. The
  `python-magic` wheel needs a system `libmagic.so.1`, which Render's native
  Python image does not ship and the native runtime cannot `apt-get`. The API
  therefore depends on `python-magic-standalone`, which bundles
  `magic/libmagic.so.1` and `magic.mgc` in the wheel and resolves them first.
- **Cold starts.** Free API instances sleep; the first request looks like a hang.
- **Upload size.** `API_MAX_UPLOAD_MB` defaults to 200, but the free instance has
  512 MB RAM and buffers uploads to a temp file. Lower it to ~50 until a large
  file has been verified end to end.
- **Pooler mode.** Runtime traffic can use the transaction pooler (6543), but
  migrations should use the session pooler (5432). If prepared statements fail at
  runtime, move the services to 5432 as well.
- **Upstash TLS.** `celery_app.py` appends `ssl_cert_reqs=CERT_REQUIRED` to a
  `rediss://` URL when it is missing, so both services only need the plain URL.
- **Lockfiles.** `uv.lock` must be committed for `--frozen` to mean anything;
  Render only auto-provisions uv when the lock sits in the service root, hence
  the explicit `pip install uv`.
