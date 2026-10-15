import logging

from fastapi import FastAPI
# Starlette's base class also covers routing errors (unknown path 404, wrong method 405), so every
# error response uses the same {"error": {...}} envelope.
from starlette.exceptions import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


logger = logging.getLogger("backend.app.errors")

_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error_handler(request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed"
        code = _HTTP_ERROR_CODES.get(exc.status_code, f"http_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"error": {"code": code, "message": detail}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc: RequestValidationError):
        errors = [
            {"location": list(error.get("loc", ())), "message": error.get("msg", "Invalid value"), "code": error.get("type", "validation_error")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Request validation failed", "details": errors}},
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request, exc: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "conflict", "message": "The request conflicts with existing or related data"}},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request, exc: SQLAlchemyError):
        # Full details go to the server log (visible in the host's log stream), never to the client.
        logger.error("Database error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "database_unavailable", "message": "The database request could not be completed"}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request, exc: Exception):
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "An unexpected server error occurred"}},
        )
