from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """A business error returned to the client as {"error": {"code", "message"}}."""

    def __init__(self, status_code: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}


def not_found(what: str = "Not found") -> AppError:
    return AppError(404, "not_found", what)


def _body(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, **exc.extra), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _DEFAULT_CODES.get(exc.status_code, "error")
        return JSONResponse(
            _body(code, str(exc.detail)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        fields = [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            _body("validation_error", "Some fields are invalid", fields=fields),
            status_code=422,
        )
