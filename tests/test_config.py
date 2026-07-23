from pydantic import SecretStr

from app.config import Settings


def test_explicit_database_url_is_preserved() -> None:
    settings = Settings(database_url="postgresql://local:test@postgres:5432/orders")

    assert settings.resolved_database_url == "postgresql://local:test@postgres:5432/orders"


def test_database_url_is_built_from_separate_fields() -> None:
    settings = Settings(
        database_url=None,
        database_host="orders.example.internal",
        database_port=5432,
        database_name="orders",
        database_user="order_app",
        database_password=SecretStr("p@ss/word"),
        database_sslmode="require",
    )

    assert settings.resolved_database_url == (
        "postgresql://order_app:p%40ss%2Fword@orders.example.internal:5432/orders?sslmode=require"
    )


def test_nats_servers_support_multiple_bootstrap_addresses() -> None:
    settings = Settings(nats_url="nats://nats-0:4222, nats://nats-1:4222")

    assert settings.nats_servers == ["nats://nats-0:4222", "nats://nats-1:4222"]
