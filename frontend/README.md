# LinguaFlow frontend (Next.js)

**Stack:** Next.js 15 · React 19 · TypeScript · pnpm · Tailwind v4

**Learner:** http://localhost:3000/login → `/dashboard`, `/tutor`, `/speaking`, `/library`, …  
**Admin (ops):** http://localhost:3000/admin/login → `/admin/knowledge-base`, `/admin/models`, …

## Setup

```bash
cd frontend
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
pnpm install
pnpm dev
```

Start the FastAPI backend on `:8000` (`cd backend && docker compose up -d && uvicorn app.main:app --reload`).

- `/` redirects to `/login`
- `/voice` redirects to `/speaking`
- `/analysis` redirects to `/analytics`
- Mocks: set `NEXT_PUBLIC_USE_MOCKS=true` in `.env.local` (MSW in dev only)

## Scripts

| Command | Description |
|---------|-------------|
| `pnpm dev` | Dev server (Turbopack) |
| `pnpm build` | Production build |
| `pnpm start` | Serve production build |

See [`../FRONTEND_SPEC.md`](../FRONTEND_SPEC.md) and [`../API_CONTRACT.md`](../API_CONTRACT.md).
