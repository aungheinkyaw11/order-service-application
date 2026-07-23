import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import Database
from app.logging import log_event, request_id_context
from app.messaging import OrderPublisher
from app.models import OrderCreate, OrderCreatedResponse, OrderResponse

logger = logging.getLogger(__name__)


def normalize_request_id(value: str | None) -> str:
    if value is not None:
        try:
            return str(UUID(value))
        except (ValueError, AttributeError):
            pass
    return str(uuid4())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(
        settings.resolved_database_url,
        settings.dependency_connect_timeout_seconds,
        settings.dependency_command_timeout_seconds,
    )
    publisher = OrderPublisher(
        settings.nats_servers,
        settings.nats_stream,
        settings.nats_subject,
        settings.dependency_connect_timeout_seconds,
    )
    app.state.database = database
    app.state.publisher = publisher
    log_event(
        logger,
        logging.INFO,
        "api_started",
        image_version=settings.image_version,
    )
    try:
        yield
    finally:
        try:
            await asyncio.wait_for(publisher.close(), settings.shutdown_timeout_seconds)
        except TimeoutError:
            log_event(logger, logging.WARNING, "api_nats_drain_timed_out")
        try:
            await asyncio.wait_for(database.close(), settings.shutdown_timeout_seconds)
        except TimeoutError:
            log_event(logger, logging.WARNING, "api_database_close_timed_out")
        log_event(logger, logging.INFO, "api_stopped")


app = FastAPI(title="Order Service", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def internal_error(_: Request, exc: Exception) -> JSONResponse:
    log_event(logger, logging.ERROR, "unhandled_error", error=exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error"},
    )


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Response:
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        log_event(logger, logging.INFO, "request_completed", request_id=request_id)
        return response
    except Exception:
        log_event(
            logger,
            logging.ERROR,
            "request_failed",
            request_id=request_id,
            exc_info=True,
        )
        raise
    finally:
        request_id_context.reset(token)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> Response:
    try:
        await request.app.state.database.check()
    except Exception as exc:
        log_event(logger, logging.WARNING, "readiness_failed", error=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return Response(content='{"status":"ready"}', media_type="application/json")


@app.post("/orders", response_model=OrderCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, request: Request) -> OrderCreatedResponse:
    order_id = uuid4()
    request_id = request_id_context.get()
    await request.app.state.database.create_order(order_id, payload.symbol, payload.quantity)
    await request.app.state.publisher.publish(
        {
            "order_id": str(order_id),
            "symbol": payload.symbol,
            "quantity": payload.quantity,
            "request_id": request_id,
        }
    )
    log_event(
        logger,
        logging.INFO,
        "order_created",
        request_id=request_id,
        order_id=order_id,
    )
    return OrderCreatedResponse(id=order_id)


@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: UUID, request: Request) -> OrderResponse:
    order = await request.app.state.database.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    return OrderResponse.model_validate(order)
