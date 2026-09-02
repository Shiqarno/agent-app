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


class TaskNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(status_code=404, code="TASK_NOT_FOUND", message="Task not found")


class AssigneeNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(status_code=422, code="ASSIGNEE_NOT_FOUND", message="Assignee not found")


class RewardNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(status_code=404, code="REWARD_NOT_FOUND", message="Reward not found")


class InsufficientPointsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="INSUFFICIENT_POINTS",
            message="Insufficient points to redeem this reward",
        )


class InvalidTransitionError(AppError):
    def __init__(self, message: str = "Invalid task state transition") -> None:
        super().__init__(status_code=409, code="INVALID_TRANSITION", message=message)


class UnauthenticatedError(AppError):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(status_code=401, code="UNAUTHENTICATED", message=message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(status_code=403, code="FORBIDDEN", message=message)


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(status_code=401, code="INVALID_CREDENTIALS", message="Invalid credentials")


class InvalidSetupTokenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=401, code="INVALID_SETUP_TOKEN", message="Invalid setup token"
        )


class SetupAlreadyCompletedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="SETUP_ALREADY_COMPLETED",
            message="Setup has already been completed",
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
