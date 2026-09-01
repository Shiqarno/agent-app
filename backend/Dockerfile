FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY . .
RUN uv sync --frozen --extra dev

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
