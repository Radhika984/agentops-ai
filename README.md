# AgentOps AI

AgentOps AI is a platform that runs, evaluates, and safeguards other AI
agents. It is being built in gated phases according to
`agentops-ai-implementation-blueprint.md`.

## Stack

- **Backend:** FastAPI (Python 3.12) + PostgreSQL, dependency-managed with `uv`
- **Frontend:** Next.js (App Router, TypeScript)
- **Local environment:** Docker Compose

## Prerequisites

- Docker Desktop (with Docker Compose v2)

No local Python or Node installation is required to run the app — only to
run the backend test suite outside Docker (see below).

## Getting started

```powershell
copy .env.example .env
docker compose up --build
```

That's it — this is the only manual step. `docker compose up` brings up
three services:

| Service    | URL                            |
|------------|---------------------------------|
| `postgres` | `localhost:5434` (mapped from container port 5432 — 5432 is commonly already in use by other local projects) |
| `backend`  | http://localhost:8000           |
| `frontend` | http://localhost:3000           |

Note: the `backend` container talks to Postgres over the internal Docker
network at `postgres:5432` (see `docker-compose.yml`), unaffected by the
5434 host mapping — that mapping only matters if you want to connect a
host tool (e.g. `psql`) directly to the Dockerized database.

Verify:

- Backend health: `curl http://localhost:8000/api/v1/health` → `{"status":"ok"}`
- API docs: http://localhost:8000/docs
- Frontend: open http://localhost:3000 — it calls the backend health
  endpoint on load and shows the result.

## Environment variables

See `.env.example` for the full list. Notes:

- `JWT_SECRET` has no default and must be set (any long random string
  locally) — the app will not start without it.
- `GEMINI_API_KEY` is optional. The app starts and Phases 0/1 work fully
  without it; only the `/ask` endpoint (Phase 2) requires it.
- `DATABASE_URL` in `.env` uses `localhost`, which is correct when running
  the backend directly on the host. Inside Docker Compose, `backend`
  connects to Postgres via the service name `postgres` instead (overridden
  in `docker-compose.yml`, not in `.env`).

## Running the backend outside Docker

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Running tests

```powershell
cd backend
uv run pytest
```

Tests run against `TEST_DATABASE_URL` (defaults to
`agentops_test` on `localhost:5434`) — a Postgres instance must be
reachable there, e.g. via `docker compose up postgres`. The `agentops_test`
database itself must already exist (`CREATE DATABASE agentops_test;`) —
unlike `agentops_dev`, it isn't created automatically by the `postgres`
service's `POSTGRES_DB` setting.

## Project status

See `agentops-ai-implementation-blueprint.md` for the full phased roadmap
(Phase 0 through Phase 10). Implementation proceeds one phase at a time.
