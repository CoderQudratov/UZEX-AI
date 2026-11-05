"""Uvicorn entrypoint for production deployment on Render Free.

Exposes the top-level `app` ASGI instance for `uvicorn app.main:app`.
"""

from app.api.application import create_app
from app.core.config import load_settings
from app.core.logging import configure_logging

configure_logging()
settings = load_settings()
app = create_app(settings)
