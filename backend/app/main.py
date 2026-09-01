from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.db import database_is_available
from app.routers.projects import router as projects_router

app = FastAPI(title="Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(projects_router)


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    if not database_is_available():
        response.status_code = 503
        return {"status": "error", "database": "unavailable"}
    return {"status": "ok", "database": "ok"}
