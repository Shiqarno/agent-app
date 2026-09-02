from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ProjectNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(status_code=404, code="PROJECT_NOT_FOUND", message="Project not found")


class DatabaseUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503, code="DATABASE_UNAVAILABLE", message="Database unavailable"
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
