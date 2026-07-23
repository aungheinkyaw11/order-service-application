import uvicorn

from app.config import get_settings
from app.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging("api", settings.log_level)
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8000,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
