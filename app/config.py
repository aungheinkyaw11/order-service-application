from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    database_url: str | None = None
    database_host: str = "postgres"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "orders"
    database_user: str = "orders"
    database_password: SecretStr = SecretStr("orders")
    database_sslmode: str = "prefer"
    nats_url: str = "nats://nats:4222"
    nats_stream: str = "ORDERS"
    nats_subject: str = "orders.created"
    nats_consumer: str = "orders-worker"
    log_level: str = "INFO"
    processing_delay_seconds: float = Field(default=2.0, ge=0)
    dependency_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    dependency_command_timeout_seconds: float = Field(default=10.0, gt=0)
    shutdown_timeout_seconds: float = Field(default=10.0, gt=0)
    image_version: str = "local"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url

        username = quote(self.database_user, safe="")
        password = quote(self.database_password.get_secret_value(), safe="")
        database_name = quote(self.database_name, safe="")
        return (
            f"postgresql://{username}:{password}@{self.database_host}:"
            f"{self.database_port}/{database_name}?sslmode={self.database_sslmode}"
        )

    @property
    def nats_servers(self) -> list[str]:
        return [server.strip() for server in self.nats_url.split(",") if server.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
