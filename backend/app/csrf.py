from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.identity import SESSION_COOKIE_NAME

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"

_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# /login and /setup establish a *new* session rather than acting within an
# existing one, so they must not be gated by a stale/unrelated session cookie
# that happens to still be present in the browser (e.g. logging in again from
# an already-logged-in tab). /logout is deliberately NOT exempted: it mutates
# the current session and gets the same protection as any other mutation.
_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login", "/api/auth/setup"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit-cookie CSRF protection for authenticated state-changing requests.

    Applies only when a session cookie is present, since an unauthenticated
    request has no ambient credential worth protecting. GET requests are
    never checked.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _STATE_CHANGING_METHODS and request.url.path not in _CSRF_EXEMPT_PATHS:
            if request.cookies.get(SESSION_COOKIE_NAME) is not None:
                cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
                header_token = request.headers.get(CSRF_HEADER_NAME)
                if not cookie_token or not header_token or cookie_token != header_token:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "CSRF_VALIDATION_FAILED",
                                "message": "Missing or invalid CSRF token",
                            }
                        },
                    )
        return await call_next(request)
