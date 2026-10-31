import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

log = logging.getLogger("worksphere.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code:
            self.status_code = status_code
        if code:
            self.code = code


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)


class NotFound(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"

    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message)


class Conflict(AppError):
    status_code = 409
    code = "conflict"


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Invalid request", details), status_code=422)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        log.warning("integrity error: %s", exc.orig)
        return JSONResponse(_body("conflict", "The change conflicts with existing data"), status_code=409)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("internal_error", "Internal server error"), status_code=500)
