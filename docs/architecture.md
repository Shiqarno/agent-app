# Architecture

## Overview

One application codebase and one PostgreSQL database, run entirely with Docker Compose, exposed through four services:

- **Database** — PostgreSQL
- **Backend / Web application** — Python + FastAPI + synchronous SQLAlchemy + Alembic, serving the HTTP API the Web UI talks to
- **Web UI** — React + TypeScript + Vite
- **Telegram Bot** — a separate runtime process/container (`telegram-bot`), built from the same backend codebase and image, running as a Telegram long-polling client instead of an HTTP server

The Telegram Bot is **not** a separate backend or domain service: it shares the same Python package, the same SQLAlchemy models, the same Application-layer operations, and the same PostgreSQL database as the FastAPI process. It is a second entry point into one application, not a second application. Concretely:

```text
                    PostgreSQL
                        │
             shared application code
                  ┌─────┴─────┐
                  │           │
             FastAPI      Telegram Bot
                  │           │
               Web UI      Telegram
```

Architectural principles this preserves:

- one application codebase;
- one PostgreSQL database;
- FastAPI and the Telegram Bot are separate application entry points/runtime processes, not separate services with their own domain logic;
- the Telegram Bot never calls FastAPI over HTTP — it talks to the database directly through the same shared code FastAPI uses;
- the Telegram Bot directly reuses the shared Application/Domain layer, exactly like FastAPI's routers do;
- the Telegram adapter (`app/telegram/`) owns only Telegram-specific transport/presentation concerns;
- the Application layer (`app/*_operations.py`) owns use cases and authorization, for both entry points;
- the Domain layer (SQLAlchemy models) owns business invariants/lifecycle, for both entry points.

This is deliberately **not** a microservices split: there is one deployable codebase, one database, and no service-to-service network calls. Splitting the runtime into two processes is only about how each one talks to the outside world (HTTP vs. Telegram's long-polling API) — see "Telegram Bot" below.

There are no other infrastructure services beyond the four above (no Redis, no Kafka, no Kubernetes, no cloud-specific services). The application is optimized for low development cost, low infrastructure cost, fast iteration with AI coding agents, and maintainability by a small team.

## Frontend: React + TypeScript + Vite

- Large shared vocabulary with AI coding agents — the most common frontend stack, which speeds up AI-assisted development.
- Vite gives a fast dev server with hot module reload and minimal configuration.
- TypeScript satisfies the type-checking requirement on the client.
- Builds to static files, so production hosting is cheap (static hosting or a single lightweight server), with no Node process required in production.
- Routing (`src/router.tsx`) is a small hand-rolled History API wrapper (`RouterProvider`/`useRouter`/`Link`), not a routing library. The app has a handful of static routes (`/dashboard`, `/tasks`, `/tasks/new`, etc.) with no nested or dynamic segments, so a routing library would be more than the project needs (see CLAUDE.md: no new dependencies unless necessary). Revisit if routes grow dynamic segments or nesting.
- The dev server proxies `/api/*` to the `backend` container (`vite.config.ts`), and the frontend's API client (`src/api/http.ts`) defaults to a relative URL. This makes the browser's requests same-origin (`localhost:5173` for both the page and the API) rather than cross-origin to `localhost:8000` — required for the session cookie's `SameSite=Lax` to be accepted and sent back by Chrome. `VITE_API_URL` remains available for a deployment that intentionally serves the API from a separate origin.

**Open trade-off:** a server-rendered Python app (FastAPI + Jinja2 + htmx) would reduce the stack to a single language and remove the frontend build step entirely. React/TS/Vite was chosen because "web client" was specified as its own tier, implying a separable frontend, but this is worth reconsidering if the product turns out to be simple CRUD/forms with little client-side interactivity.

## Backend: Python + FastAPI + synchronous SQLAlchemy + Alembic

- FastAPI uses Python type hints natively (Pydantic models for request/response validation), which satisfies the "type checking where appropriate" requirement structurally rather than as an add-on.
- Auto-generated OpenAPI docs describe the API contract for both the frontend and AI agents without hand-written documentation.
- SQLAlchemy is used **synchronously** rather than with an async driver. This trades some performance ceiling for a simpler, easier-to-debug mental model, which fits a small team. It can move to async later if there's an actual throughput need.
- **psycopg (psycopg 3, `psycopg[binary]`)** is the Postgres driver, not psycopg2. It's the actively maintained driver, ships binary wheels (no local Postgres build dependencies needed), and works with SQLAlchemy 2.0's sync engine via the `postgresql+psycopg://` dialect.
- Alembic manages schema migrations against the SQLAlchemy models.

**Open trade-off:** Django would provide migrations, an admin UI, and auth out of the box, lowering dev cost further for a CRUD-heavy app, at the cost of more implicit framework behavior. FastAPI was chosen for being lighter-weight and more API-first; revisit if the product turns out to be admin/CRUD-heavy.

## Telegram Bot

A second presentation/adapter channel onto the same application, alongside the Web UI — not a second backend. It runs as its own Docker Compose service (`telegram-bot`), built from the same `./backend` image as the FastAPI process, but started with a different command (`python -m app.telegram.bot`) that runs `python-telegram-bot`'s long-polling loop instead of `uvicorn`. It has no exposed port: it only makes outbound requests to the Telegram API and never receives inbound HTTP traffic, and it does not run migrations.

Request flow through the Telegram adapter mirrors the Web request flow through FastAPI's routers, ending at the same layers:

```text
Telegram
   ↓
Telegram adapter (app/telegram/handlers, views, keyboards)
   ↓
Application operations (app/*_operations.py)
   ↓
Domain (SQLAlchemy models)
   ↓
PostgreSQL
```

- `app/telegram/handlers/` — one module per feature area, translating a Telegram `Update`/callback into a call against the shared Application-layer operations (`app/task_operations.py`, `app/reward_operations.py`, `app/points_operations.py`, `app/goal_operations.py`, `app/user_operations.py`, `app/telegram_identity.py`), the same operations the FastAPI routers call. Each handler function opens its own synchronous SQLAlchemy session and runs the DB work in a thread (`asyncio.to_thread`), since `python-telegram-bot` is async and this project's DB layer is not.
- `app/telegram/views/` — pure functions turning domain state into message text.
- `app/telegram/keyboards/` — pure functions building inline keyboards; callback data identifies an entity for routing only and is never trusted for authorization — the Application layer re-verifies role/existence/state on every call, exactly as it does for an HTTP request.

The Telegram Bot **never calls the FastAPI process over HTTP**. It has its own direct `DATABASE_URL` connection to PostgreSQL and imports the same Application/Domain-layer Python code in-process — the same relationship FastAPI's own routers have to that code, just from a different entry point. Business rules, authorization, and concurrency guarantees live once, in the Application layer, and apply identically regardless of which adapter (Web or Telegram) invoked them.

## Database: PostgreSQL

- Single official `postgres` image, one named Docker volume for durability across restarts.
- No separate admin UI container (e.g. pgAdmin) at this stage — `psql` via `make shell-db` is sufficient and keeps the Compose file minimal.

## Infrastructure: Docker Compose only

Four services — `db`, `backend`, `frontend`, `telegram-bot` — and nothing else. `backend` and `telegram-bot` are two different runtime processes/containers built from the same `./backend` image and codebase (see "Telegram Bot" above), not two independently deployable services. Explicitly excluded at this stage: Kubernetes, a microservices split, Redis, Kafka, and any cloud-specific services. These would add operational and cognitive overhead disproportionate to what this application needs, and none of them are required by any current product need. Introducing any of them should be a deliberate decision made when there's a concrete requirement (e.g. a background job queue), not a default.

A single `docker-compose.yml` is used, without a separate `docker-compose.override.yml`. It currently runs the frontend via the Vite dev server (bind-mounted source, hot reload) and the backend via `uvicorn --reload`, which is what local development actually needs right now. A production-oriented build (e.g. a static frontend build served by a minimal web server) can be introduced later, as a deliberate step, once deployment is being set up — see "Deploying later" below.

## Authentication

Authentication and authorization are separate concerns:

```
session cookie → get_current_user() → User → require_adult() → domain logic
```

- **Credentials** (`UserCredential`) are a separate 1:1 table from `User` (`user_id`, `email`, `password_hash`), not columns on `User` itself. `User` stays focused on domain identity (`id`, `name`, `role`); not every `User` has credentials (see below).
- **Passwords** are hashed with Argon2id (`argon2-cffi`), never stored or logged in plaintext, never returned by any API response.
- **Sessions** (`UserSession`) are server-side, stored in Postgres — no JWT, no Redis. The client holds only an opaque, high-entropy random token (`secrets.token_urlsafe`); the database stores only its SHA-256 hash, so a leaked database row can't be replayed as a session. Sessions have a fixed 7-day absolute expiration (`expires_at`); expired sessions are rejected and opportunistically deleted on next use, rather than refreshed or rotated.
- **Identity** is carried by an `HttpOnly`, `SameSite=Lax` cookie (`session_token`), never exposed to frontend JavaScript and never present in a JSON response. `get_current_user()` is the single place that resolves a request's identity from that cookie; every existing authorization dependency (`require_adult`, etc.) is unchanged and keeps building on top of it.
- **CSRF protection** is centralized in one middleware (`app/csrf.py`), not scattered per-router. It's a double-submit-cookie check: a second, JS-readable `csrf_token` cookie must match an `X-CSRF-Token` header on every state-changing request (`POST`/`PUT`/`PATCH`/`DELETE`) once a session cookie is present. `GET` is never checked. `/api/auth/login` and `/api/auth/setup` are explicitly exempt, since they establish a session rather than act within one — a stale, unrelated cookie in the browser must not block a fresh login attempt.
- **`X-User-Id` is gone** as an authentication mechanism. It was the placeholder identity header used before this issue; the session cookie is now the only thing `get_current_user()` will accept.
- **Bootstrapping**: there is no self-registration. The very first Adult is created through `POST /api/auth/setup`, a one-time endpoint gated by an `INITIAL_SETUP_TOKEN` secret (environment-configured, never committed) and only usable while the `users` table is empty. Every subsequent User is created through the existing `POST /api/users` (Adult-only) — but that endpoint creates a domain `User` only, with **no credentials**. Such a User is a fully valid participant in every other part of the system (discoverable, assignable, can be assigned points, etc.) but cannot log in until they're activated (see below).
- **Onboarding / activation**: `POST /api/users` also creates a `UserActivation` — a single-use, opaque token (same `secrets.token_urlsafe` + SHA-256-hash-at-rest approach as sessions) valid for 72 hours, stored alongside the `User` in the same transaction. `UserActivation` is a shared mechanism, not a Web-specific one: it is the one-time activation token behind *both* onboarding channels, each consuming it into its own channel-specific credential:

  ```text
  UserActivation
        │
        ├── Web activation
        │      └── UserCredential
        │
        └── Telegram activation
               └── TelegramIdentity
  ```

  Token generation always happens server-side. The raw token is returned once, in the `POST /api/users` response (`activation_token`), so the Web UI can build both an activation link and a Telegram deep link (`https://t.me/<bot_username>?start=<token>`) from it; only its SHA-256 hash is ever persisted, so the raw token itself is never stored in plaintext and can't be recovered from the database afterward. `POST /api/users/{user_id}/activation` regenerates a fresh token for a User whose original was lost or has expired — it overwrites the same `UserActivation` row in place (invalidating whatever token existed before it) and is refused once that User already has a `TelegramIdentity`, since a User connected to Telegram doesn't need Web activation to have been used up first for that decision.

  `POST /api/auth/activate` (public, no session/CSRF required) is the Web-side consumer: given a valid, unused, unexpired token plus a new email/password, it creates the `UserCredential`, marks the token used, and immediately issues a session — the same auto-login behavior as `/setup`. An invalid, expired, or already-used token all produce the identical `INVALID_ACTIVATION_TOKEN` error, so a token's state can't be probed from the outside. A credential-less User attempting to log in gets the same generic `INVALID_CREDENTIALS` as any other failed login — there is no separate "not yet activated" error. The Telegram-side consumer (`activate_telegram_identity` in `app/telegram_identity.py`, invoked from `/start <token>`) resolves the same token through the same shared lookup (`app/activation.py::resolve_activation`) and, on success, creates or updates a `TelegramIdentity` instead of a `UserCredential` — see "Telegram Bot" above. Creating a User and activating it (through either channel) remain deliberately unlinked beyond the token: the creating Adult has no ownership record over the resulting account.

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

Because the app is a plain Docker Compose setup with no orchestration-specific dependencies, it can be deployed to a single VM, a managed container platform (e.g. Fly.io, Render, ECS on Fargate), or similar, by building the same `backend` and `frontend` images and pointing `DATABASE_URL` at a managed Postgres instance. The `telegram-bot` process is the same `backend` image run with a different command, so it needs no separate build step, only its own running container/process (with `TELEGRAM_BOT_TOKEN` set) alongside `backend`. No code changes are required to move off Compose for local dev; only the deployment target's own configuration (build/run commands, environment variables) needs to be added, which is intentionally not part of this repository yet.
