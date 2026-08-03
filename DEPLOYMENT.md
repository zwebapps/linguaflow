# Deploying DeutschFlow (free tier)

One app, five services — each on the free tier it's genuinely good at:

```
Browser ── Vercel (Next.js frontend)
              │  HTTPS / JSON / SSE
              ▼
        Google Cloud Run ── FastAPI + LangChain + ingestion worker (one container)
           │         │         │
           ▼         ▼         ▼
       Supabase   Upstash   Qdrant Cloud
       Postgres   Redis     vectors
              │
              ▼
         OpenRouter ── LLM / STT
```

Cloud Run is stateless, so everything that must persist lives in the managed
services. Locally the same env vars point at `docker-compose.yml`; in
production they point at the cloud — the code never changes.

## 0. One-time accounts

| Service | Create | Copy | Becomes |
|---|---|---|---|
| supabase.com | project | connection string | `DATABASE_URL` |
| upstash.com | Redis database | TLS URL | `REDIS_URL` |
| cloud.qdrant.io | free cluster | URL + API key | `QDRANT_URL`, `QDRANT_API_KEY` |
| Google Cloud | project + billing enabled | — | (host) |
| vercel.com | import repo | — | (frontend) |

## 1. Backend → Render (no credit card) **or** Cloud Run

### Render — recommended when you don't want to attach billing

Render's free web service needs no payment method. The repo ships
`render.yaml`, so:

1. Push this repo to GitHub (Render deploys from it).
2. Render dashboard → **New → Blueprint** → pick the repo → it reads
   `render.yaml` and proposes `deutschflow-api` (Docker, free, Frankfurt).
3. Render prompts for the `sync: false` env vars — paste them from
   `backend/deploy/.env.cloudrun` (that file is gitignored and holds your real
   values). `CORS_ORIGINS`/`PUBLIC_APP_URL` can start as
   `https://localhost:3000` and be corrected after the Vercel deploy.
4. Apply. First boot migrates, bootstraps the admin, and seeds the corpus.

Measured: the image runs at **~310 MB under a 512 MB cap** — fits the free
plan with headroom, provided `EMBEDDING_BACKEND=openrouter` (the `local`
backend pulls ~2 GB of torch and cannot fit).

Free-plan behaviour: the service **sleeps after 15 idle minutes**, so the
first request afterwards takes ~50 s. Ingestion (uploads, RSS) only runs while
the service is awake — fine in practice, since uploads happen while an admin
is using the app.

### Cloud Run — if you have an open billing account

Requires an **open** billing account linked to the project (free quota still
demands a card on file):

```bash
gcloud billing projects link <PROJECT_ID> --billing-account=<ACCOUNT_ID>
```

Then the section below.

## 1b. Cloud Run details

Secrets live in `backend/deploy/.env.cloudrun` (**gitignored** — never commit
it). Fill it from `backend/deploy/.env.cloudrun` comments; three formats bite:

- **Supabase**: use the **session pooler** URI (`aws-0-<region>.pooler.supabase.com:5432`,
  username `postgres.<project-ref>`) with the `postgresql+asyncpg://` scheme.
  The direct `db.<ref>.supabase.co` host is **IPv6-only** — Cloud Run cannot
  reach it.
- **Upstash**: scheme must be `rediss://` (TLS), not `redis://`.
- **Qdrant**: append `:6333` to the cluster URL.

Production boot refuses weak values by design: `JWT_SECRET` ≥ 32 chars,
`ADMIN_PASSWORD` ≥ 12 chars and not the default. `SEED_ON_BOOT=true` fills the
library with the starter German corpus on first boot (off by default in
production).

```bash
# once
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>

# every deploy / secret rotation
cd backend
./deploy/cloudrun.sh
```

The script deploys from source with the repo `Dockerfile`; the container runs
uvicorn **and** the ingestion worker (free tiers give one process — without
the worker, uploads sit "pending" forever). Migrations + admin bootstrap +
seeding run in the app's own startup.

## 2. Frontend → Vercel

Import the GitHub repo, **root directory `frontend`**, one env var:

```
NEXT_PUBLIC_API_URL=https://<your-service>.run.app/api/v1
```

`NEXT_PUBLIC_*` is baked at build time — changing it later requires a
redeploy. Never put secrets in `NEXT_PUBLIC_*`; all real secrets stay on
Cloud Run.

## 3. Close the loop

After both URLs exist, set the final three in `deploy/.env.cloudrun` and rerun
the script:

```
CORS_ORIGINS=https://<your-app>.vercel.app
PUBLIC_APP_URL=https://<your-app>.vercel.app
OAUTH_CALLBACK_BASE=https://<your-service>.run.app   # only needed for OAuth
```

Sign in at the Vercel URL — the admin account is `ADMIN_EMAIL` /
`ADMIN_PASSWORD` from the env file (Ops portal link on the login page).

## Known free-tier behaviour

- **Cloud Run scales to zero** and throttles CPU between requests: the
  ingestion worker only processes while traffic keeps an instance warm — fine
  in practice (uploads happen while an admin is using the app). Unattended
  ingestion needs `--no-cpu-throttling --min-instances 1`, which leaves the
  free quota (~$10–15/mo).
- **Ephemeral disk**: ingested content persists (Postgres + Qdrant), original
  upload files and the dev email outbox don't survive a redeploy.
- **Email verification** uses the console sink (`EMAIL_SINK=console`): links
  are logged, not sent. Wire a real provider in `app/services/mailer.py`
  before real users.
- **LLM spend** is the one genuinely metered thing: point Admin → AI routes at
  `:free` OpenRouter models to stay at $0.
