import asyncio
import json
import logging
from uuid import UUID

import nats
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from app.config import get_settings
from app.database import Database
from app.logging import configure_logging, log_event, request_id_context
from app.messaging import ensure_stream

logger = logging.getLogger(__name__)


async def process_message(message: object, database: Database, delay: float) -> None:
    data = json.loads(message.data)
    order_id = UUID(data["order_id"])
    request_id = str(UUID(data["request_id"]))
    token = request_id_context.set(request_id)
    try:
        existing = await database.get_order(order_id)
        if existing is None:
            log_event(
                logger,
                logging.ERROR,
                "order_not_found",
                request_id=request_id,
                order_id=order_id,
            )
            await message.term()
            return
        if existing["status"] == "pending":
            await asyncio.sleep(delay)
            updated = await database.fill_order(order_id)
            event = "order_filled" if updated else "order_already_processed"
        else:
            event = "order_already_processed"
        await message.ack()
        log_event(
            logger,
            logging.INFO,
            event,
            request_id=request_id,
            order_id=order_id,
        )
    finally:
        request_id_context.reset(token)


async def handle_message(message: object, database: Database, delay: float) -> None:
    try:
        await process_message(message, database, delay)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "order_processing_failed",
            error=exc,
            exc_info=True,
        )
        await message.nak()


async def run() -> None:
    settings = get_settings()
    configure_logging("worker", settings.log_level)
    database = Database(
        settings.resolved_database_url,
        settings.dependency_connect_timeout_seconds,
        settings.dependency_command_timeout_seconds,
    )
    await database.connect()
    client = await nats.connect(
        settings.nats_servers,
        name="orders-worker",
        connect_timeout=settings.dependency_connect_timeout_seconds,
        drain_timeout=settings.shutdown_timeout_seconds,
    )
    jetstream = client.jetstream()
    await ensure_stream(jetstream, settings.nats_stream, settings.nats_subject)
    subscription = await jetstream.pull_subscribe(
        settings.nats_subject,
        durable=settings.nats_consumer,
        stream=settings.nats_stream,
        config=ConsumerConfig(
            durable_name=settings.nats_consumer,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=30,
            deliver_policy=DeliverPolicy.ALL,
            max_demax_deliver=5,
        ),
    )
    log_event(
        logger,
        logging.INFO,
        "worker_started",
        image_version=settings.image_version,
    )
    try:
        while True:
            try:
                messages = await subscription.fetch(batch=1, timeout=1)
            except NatsTimeoutError:
                continue
            for message in messages:
                await handle_message(message, database, settings.processing_delay_seconds)
    finally:
        try:
            await asyncio.wait_for(client.drain(), settings.shutdown_timeout_seconds)
        except TimeoutError:
            await client.close()
            log_event(logger, logging.WARNING, "worker_nats_drain_timed_out")
        try:
            await asyncio.wait_for(database.close(), settings.shutdown_timeout_seconds)
        except TimeoutError:
            log_event(logger, logging.WARNING, "worker_database_close_timed_out")
        log_event(logger, logging.INFO, "worker_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
