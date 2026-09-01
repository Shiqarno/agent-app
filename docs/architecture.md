# Architecture

## Overview

A simple 3-tier web application, run entirely with Docker Compose:

- **Frontend** — React + TypeScript + Vite
- **Backend** — Python + FastAPI + synchronous SQLAlchemy + Alembic
- **Database** — PostgreSQL

There are no other infrastructure services (no Redis, no Kafka, no Kubernetes, no microservices, no cloud-specific services). The application is optimized for low development cost, low infrastructure cost, fast iteration with AI coding agents, and maintainability by a small team.

## Frontend: React + TypeScript + Vite

- Large shared vocabulary with AI coding agents — the most common frontend stack, which speeds up AI-assisted development.
- Vite gives a fast dev server with hot module reload and minimal configuration.
- TypeScript satisfies the type-checking requirement on the client.
- Builds to static files, so production hosting is cheap (static hosting or a single lightweight server), with no Node process required in production.

**Open trade-off:** a server-rendered Python app (FastAPI + Jinja2 + htmx) would reduce the stack to a single language and remove the frontend build step entirely. React/TS/Vite was chosen because "web client" was specified as its own tier, implying a separable frontend, but this is worth reconsidering if the product turns out to be simple CRUD/forms with little client-side interactivity.

## Backend: Python + FastAPI + synchronous SQLAlchemy + Alembic

- FastAPI uses Python type hints natively (Pydantic models for request/response validation), which satisfies the "type checking where appropriate" requirement structurally rather than as an add-on.
- Auto-generated OpenAPI docs describe the API contract for both the frontend and AI agents without hand-written documentation.
- SQLAlchemy is used **synchronously** rather than with an async driver. This trades some performance ceiling for a simpler, easier-to-debug mental model, which fits a small team. It can move to async later if there's an actual throughput need.
- **psycopg (psycopg 3, `psycopg[binary]`)** is the Postgres driver, not psycopg2. It's the actively maintained driver, ships binary wheels (no local Postgres build dependencies needed), and works with SQLAlchemy 2.0's sync engine via the `postgresql+psycopg://` dialect.
- Alembic manages schema migrations against the SQLAlchemy models.

**Open trade-off:** Django would provide migrations, an admin UI, and auth out of the box, lowering dev cost further for a CRUD-heavy app, at the cost of more implicit framework behavior. FastAPI was chosen for being lighter-weight and more API-first; revisit if the product turns out to be admin/CRUD-heavy.

## Database: PostgreSQL

- Single official `postgres` image, one named Docker volume for durability across restarts.
- No separate admin UI container (e.g. pgAdmin) at this stage — `psql` via `make shell-db` is sufficient and keeps the Compose file minimal.

## Infrastructure: Docker Compose only

Three services — `db`, `backend`, `frontend` — and nothing else. Explicitly excluded at this stage: Kubernetes, microservices, Redis, Kafka, and any cloud-specific services. These would add operational and cognitive overhead disproportionate to a simple 3-tier application run by a small team, and none of them are required by any current product need. Introducing any of them should be a deliberate decision made when there's a concrete requirement (e.g. a background job queue), not a default.

A single `docker-compose.yml` is used, without a separate `docker-compose.override.yml`. It currently runs the frontend via the Vite dev server (bind-mounted source, hot reload) and the backend via `uvicorn --reload`, which is what local development actually needs right now. A production-oriented build (e.g. a static frontend build served by a minimal web server) can be introduced later, as a deliberate step, once deployment is being set up — see "Deploying later" below.

## Migrations

Alembic migrations are **never run automatically** (not on backend container startup, not implicitly by any script). They are an explicit step, run via:

- `make migrate name=<message>` — generate a new revision from model changes.
- `make upgrade` — apply pending migrations.

This avoids surprise schema changes on every container start, and keeps migration application an intentional action in both development and (later) deployment.

## Local development workflow

The only tools required on the host machine are Docker, Docker Compose, and `make`. All application tooling (Python, Node, and their dependencies) runs inside containers, so there is nothing else to install locally. Common tasks (`up`, `down`, `test`, `lint`, `typecheck`, `migrate`, `upgrade`) are wrapped in the root `Makefile`.

## Testing & static analysis

- **Backend:** pytest for tests (using FastAPI's test client), Ruff for linting/formatting, mypy for type checking.
- **Frontend:** Vitest + React Testing Library for tests, ESLint + typescript-eslint for linting, Prettier for formatting, `tsc --noEmit` for type checking.

End-to-end testing (e.g. Playwright) is deliberately deferred until there's an actual product surface worth covering — adding it now would be complexity ahead of need.

## Repository structure

A flat monorepo, split by tier, with no shared-library indirection until there is actual shared code to justify it:

```
/
├── frontend/
├── backend/
├── docs/
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Deploying later

Because the app is a plain Docker Compose setup with no orchestration-specific dependencies, it can be deployed to a single VM, a managed container platform (e.g. Fly.io, Render, ECS on Fargate), or similar, by building the same `backend` and `frontend` images and pointing `DATABASE_URL` at a managed Postgres instance. No code changes are required to move off Compose for local dev; only the deployment target's own configuration (build/run commands, environment variables) needs to be added, which is intentionally not part of this repository yet.
