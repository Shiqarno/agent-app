# Project

A simple 3-tier web application: React/TypeScript frontend, FastAPI backend, PostgreSQL database, orchestrated locally with Docker Compose.

See [docs/architecture.md](docs/architecture.md) for the architecture and the rationale behind the main technology decisions.

## Requirements

- Docker
- Docker Compose
- make

No other local installation is required — all tooling runs inside containers.

## Quickstart

```
cp .env.example .env
make up
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (health check at `/health`)
- Database: localhost:5432

## Common tasks

| Command | Description |
| --- | --- |
| `make up` | Start all services |
| `make down` | Stop all services |
| `make test` | Run backend and frontend test suites |
| `make lint` | Run linters |
| `make typecheck` | Run type checkers |
| `make migrate name=<message>` | Generate a new Alembic migration |
| `make upgrade` | Apply migrations to the database |

Migrations are never run automatically — always run `make upgrade` explicitly after pulling new migrations or starting from a fresh database.
