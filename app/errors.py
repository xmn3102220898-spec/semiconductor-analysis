"""Uniform error responses and exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.observability import get_logger, get_request_id


logger = get_logger(__name__)


class AppError(Exception):
    """Business error carrying an HTTP status and stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _error_payload(
    code: str,
    message: str,
    detail: Any = None,
    details: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": get_request_id(),
    }
    if details is not None:
        error["details"] = details

    payload: dict[str, Any] = {"error": error}
    if detail is not None:
        # Keep FastAPI's original "detail" field during the migration.
        payload["detail"] = detail
    return payload


def _status_code_for(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "REQUEST_ERROR")


async def app_error_handler(
    request: Request,
    exc: AppError,
) -> JSONResponse:
    logger.warning(
        "business_error",
        extra={
            "event": "business_error",
            "error_code": exc.code,
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            exc.code,
            exc.message,
            detail=exc.message,
            details=exc.details,
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    message = str(exc.detail)
    code = _status_code_for(exc.status_code)

    logger.warning(
        "http_error",
        extra={
            "event": "http_error",
            "error_code": code,
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code, message, detail=exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())

    logger.warning(
        "request_validation_error",
        extra={
            "event": "request_validation_error",
            "method": request.method,
            "path": request.url.path,
            "status_code": 422,
            "validation_errors": errors,
        },
    )
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            detail=errors,
            details=errors,
        ),
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={
            "event": "unhandled_exception",
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
        },
    )
    return unexpected_error_response()


def unexpected_error_response() -> JSONResponse:
    """Build the same internal-error response from middleware."""
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            "INTERNAL_ERROR",
            "服务器内部错误",
            detail="服务器内部错误",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(Exception, unexpected_exception_handler)
