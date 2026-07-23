import asyncio
from pathlib import Path

from app.config import get_settings
from app.database import run_migrations
from app.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging("migration", settings.log_level)
    asyncio.run(
        run_migrations(
            settings.resolved_database_url,
            Path("migrations"),
            settings.dependency_connect_timeout_seconds,
            settings.dependency_command_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
