from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import database_is_available
from app.errors import DatabaseUnavailableError, register_error_handlers
from app.routers.projects import router as projects_router
from app.routers.rewards import router as rewards_router
from app.routers.tasks import router as tasks_router
from app.routers.users import router as users_router

app = FastAPI(title="Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(projects_router)
app.include_router(rewards_router)
app.include_router(tasks_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    if not database_is_available():
        raise DatabaseUnavailableError()
    return {"status": "ok", "database": "ok"}
