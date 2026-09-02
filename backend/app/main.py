from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import database_is_available
from app.errors import DatabaseUnavailableError, register_error_handlers
from app.routers.projects import router as projects_router

app = FastAPI(title="Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    if not database_is_available():
        raise DatabaseUnavailableError()
    return {"status": "ok", "database": "ok"}
