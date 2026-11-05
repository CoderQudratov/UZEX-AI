"""ASGI composition for Phase 5 Backend Integration.

Production-ready, low-latency, read-only DuckDB warehouse and Gemini integration.
"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app.agent.gemini_client import GeminiPlanner
from app.agent.query_executor import QueryExecutor
from app.agent.semantic_router import SemanticRouter
from app.api.body_limit import BodyLimit
from app.core.config import Settings, load_settings
from app.core.errors import ErrorCode, ErrorDetail, ErrorEnvelope
from app.services.chat_models import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

logger = logging.getLogger("uzex.events")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
MAX_BODY_BYTES = 65536
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "static"


def error_response(status: int, code: ErrorCode, message: str) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _init_components(
    app: FastAPI,
    settings: Settings,
    router: SemanticRouter | None,
    chat_service: ChatService | None,
) -> None:
    if chat_service is not None:
        app.state.chat_service = chat_service
        if hasattr(chat_service, "router") and hasattr(chat_service.router, "engine"):
            app.state.engine = chat_service.router.engine
    elif router is not None:
        app.state.chat_service = ChatService(
            router, max_concurrency=settings.max_concurrent_queries
        )
        app.state.engine = router.engine
    elif settings.database_path.is_file():
        try:
            engine = QueryExecutor(settings)
            planner = None
            if settings.gemini_api_key and settings.gemini_model:
                try:
                    planner = GeminiPlanner(settings)
                except Exception:
                    planner = None
            app_router = SemanticRouter(
                engine, planner, max_concurrency=settings.max_concurrent_queries
            )
            app.state.engine = engine
            app.state.chat_service = ChatService(
                app_router, max_concurrency=settings.max_concurrent_queries
            )
        except Exception:
            app.state.engine = None
            app.state.chat_service = None


def create_app(
    settings: Settings | None = None,
    router: SemanticRouter | None = None,
    chat_service: ChatService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        loaded_settings = settings if settings is not None else load_settings()
        application.state.settings = loaded_settings
        application.state.ready = False

        if getattr(application.state, "chat_service", None) is None:
            _init_components(application, loaded_settings, router, chat_service)

        application.state.ready = (
            getattr(application.state, "engine", None) is not None
            and getattr(application.state, "chat_service", None) is not None
        )
        logger.info("startup")
        try:
            yield
        finally:
            logger.info("shutdown")
            application.state.ready = False
            service = getattr(application.state, "chat_service", None)
            planner = getattr(getattr(service, "router", None), "planner", None)
            if planner is not None and callable(getattr(planner, "aclose", None)):
                await planner.aclose()
            engine = getattr(application.state, "engine", None)
            warehouse = getattr(engine, "warehouse", None)
            if warehouse is not None and callable(getattr(warehouse, "close", None)):
                warehouse.close()
            if hasattr(application.state, "chat_service"):
                del application.state.chat_service
            if hasattr(application.state, "engine"):
                del application.state.engine
            if hasattr(application.state, "settings"):
                del application.state.settings

    application = FastAPI(
        title="UZEX AI",
        lifespan=lifespan,
        debug=False,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Initial state setup
    application.state.ready = False
    application.state.engine = None
    application.state.chat_service = None
    if settings is not None:
        application.state.settings = settings
        _init_components(application, settings, router, chat_service)
        application.state.ready = (
            application.state.engine is not None and application.state.chat_service is not None
        )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )

    application.add_middleware(BodyLimit, maximum=MAX_BODY_BYTES)

    @application.middleware("http")
    async def request_size_guard(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    return error_response(413, ErrorCode.INVALID_REQUEST, "Payload too large")
            except ValueError:
                return error_response(400, ErrorCode.INVALID_REQUEST, "Invalid Content-Length")
        return await call_next(request)

    @application.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @application.get("/", include_in_schema=False)
        async def root() -> Any:
            index_file = STATIC_DIR / "index.html"
            if index_file.is_file():
                return FileResponse(str(index_file))
            return {"status": "ok"}

    @application.get("/api/v1/status")
    async def api_status(request: Request) -> dict[str, Any]:
        app_settings = getattr(request.app.state, "settings", None)
        engine = getattr(request.app.state, "engine", None)
        return {
            "status": "ready" if getattr(request.app.state, "ready", False) else "starting",
            "app_env": app_settings.app_env if app_settings else "unknown",
            "dataset_version": engine.source.version if engine else "unavailable",
            "gemini_model": app_settings.gemini_model if app_settings else None,
            "warehouse_ready": engine is not None,
        }

    @application.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: Request, body: ChatRequest) -> Any:
        chat_service_instance: ChatService | None = getattr(request.app.state, "chat_service", None)
        if chat_service_instance is None:
            return error_response(503, ErrorCode.ERROR, "Service not ready")
        return await chat_service_instance.chat(body.message)

    @application.post("/api/v1/chat/stream")
    async def chat_stream(request: Request, body: ChatRequest) -> Any:
        chat_service_instance: ChatService | None = getattr(request.app.state, "chat_service", None)
        if chat_service_instance is None:
            return error_response(503, ErrorCode.ERROR, "Service not ready")

        async def event_generator():
            yield f"data: {json.dumps({'status': 'PROCESSING'})}\n\n"
            response = await chat_service_instance.chat(body.message)
            yield f"data: {response.model_dump_json()}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError):
        return error_response(422, ErrorCode.INVALID_REQUEST, "Invalid request")

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        code, message = {
            400: (ErrorCode.INVALID_REQUEST, "Invalid request"),
            404: (ErrorCode.ROUTE_NOT_FOUND, "Route not found"),
            405: (ErrorCode.METHOD_NOT_ALLOWED, "Method not allowed"),
            413: (ErrorCode.INVALID_REQUEST, "Payload too large"),
        }.get(error.status_code, (ErrorCode.HTTP_ERROR, "Request could not be completed"))
        return error_response(error.status_code, code, message)

    @application.exception_handler(Exception)
    async def internal_error(_request: Request, _error: Exception):
        logger.error("internal_error")
        return error_response(500, ErrorCode.ERROR, "Internal service error")

    return application
