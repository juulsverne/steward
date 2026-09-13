"""Steward entry point: uv run uvicorn agent.server:app --no-proxy-headers.

Web setup is validated here. Importing config/core modules does not start the API.
The generic starter /ask route is absent from the Steward application.
"""

from .api import create_app

app = create_app()
