.PHONY: up down build logs test test-backend test-frontend lint lint-backend lint-frontend typecheck typecheck-backend typecheck-frontend migrate upgrade shell-backend shell-db

up:
	docker compose up

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

test: test-backend test-frontend

test-backend:
	docker compose run --rm backend pytest

test-frontend:
	docker compose run --rm frontend npm test

lint: lint-backend lint-frontend

lint-backend:
	docker compose run --rm backend ruff check .

lint-frontend:
	docker compose run --rm frontend npm run lint

typecheck: typecheck-backend typecheck-frontend

typecheck-backend:
	docker compose run --rm backend mypy app

typecheck-frontend:
	docker compose run --rm frontend npm run typecheck

migrate:
	docker compose run --rm backend alembic revision --autogenerate -m "$(name)"

upgrade:
	docker compose run --rm backend alembic upgrade head

shell-backend:
	docker compose exec backend bash

shell-db:
	docker compose exec db psql -U $${POSTGRES_USER:-app} -d $${POSTGRES_DB:-app}
