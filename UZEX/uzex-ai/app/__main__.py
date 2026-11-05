"""Supported server entrypoint; suppresses all payload-bearing third-party logs."""

import logging
import os

import uvicorn

from app.api.application import create_app
from app.core.config import ConfigurationError, load_settings
from app.core.logging import configure_logging


def main() -> int:
    configure_logging()
    try:
        settings = load_settings()
        port = int(os.environ.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except (ConfigurationError, ValueError):
        logging.getLogger("uzex.events").error("startup_failed")
        return 1
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 -- Docker/Render must bind to all interfaces
        port=port,
        access_log=False,
        log_config=None,
        server_header=False,
        limit_concurrency=settings.max_concurrent_queries + 8,
        timeout_keep_alive=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
