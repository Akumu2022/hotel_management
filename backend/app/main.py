import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin,
    auth,
    billing,
    forwarder,
    hotel,
    ordering,
    orders_board,
    payments,
    public,
    reports,
    riders,
)
from app.core.config import get_config
from app.core.errors import install_error_handlers

logger = logging.getLogger("app")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app() -> FastAPI:
    _configure_logging()
    get_config().check_secrets()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = None
        if os.environ.get("RUN_JOBS", "1") == "1":
            from app.core.db import SessionLocal
            from app.services.jobs import loop

            task = asyncio.create_task(loop(SessionLocal))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Hotel Food Ordering API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_config().cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        logger.info(
            "request",
            extra={
                "extra_fields": {
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - start) * 1000, 1),
                }
            },
        )
        return response

    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth.router)
    v1.include_router(admin.router)
    v1.include_router(hotel.router)
    v1.include_router(public.router)
    v1.include_router(ordering.router)
    v1.include_router(payments.customer)
    v1.include_router(payments.hotel)
    v1.include_router(payments.admin)
    v1.include_router(orders_board.hotel)
    v1.include_router(orders_board.public)
    v1.include_router(orders_board.admin)
    v1.include_router(reports.hotel)
    v1.include_router(reports.admin)
    v1.include_router(riders.public)
    v1.include_router(riders.rider)
    v1.include_router(riders.admin)
    v1.include_router(riders.dispatch)
    v1.include_router(billing.hotel)
    v1.include_router(billing.admin)
    v1.include_router(billing.rider)
    v1.include_router(forwarder.device)
    v1.include_router(forwarder.hotel)
    v1.include_router(forwarder.admin)
    app.include_router(v1)

    # Development: serve uploaded photos from the local media folder (R2 in production).
    cfg = get_config()
    if cfg.media_url.startswith("/"):
        Path(cfg.media_dir).mkdir(parents=True, exist_ok=True)
        app.mount(cfg.media_url, StaticFiles(directory=cfg.media_dir), name="media")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
