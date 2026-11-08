"""The uvicorn entry point of the web interface."""

import logging
import os
from pathlib import Path

import litellm

from coderagent.config.loader import load_config
from coderagent.core.protocols import ModelBackend

logger = logging.getLogger("coderagent.web")

LOOPBACK = ("127.0.0.1", "localhost", "::1")
"""The addresses that only the user of the machine can reach."""


def serve(
    cwd: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    config_spec: list[str] | None = None,
    model: ModelBackend | None = None,
    permission_mode: str | None = None,
) -> None:
    """Start the web interface and serve it until the user stops it."""
    import uvicorn

    from coderagent.web.app import create_app

    litellm.suppress_debug_info = True
    """litellm prints banners to stdout, which would break the event stream."""
    config = load_config(config_spec or [], cwd=cwd)
    os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = str(config.model.max_retries)
    """The retries of the model come from the environment, not from the configuration."""
    app = create_app(
        config,
        cwd,
        model=model,
        config_spec=config_spec or [],
        permission_mode=permission_mode,
    )
    if host not in LOOPBACK:
        logger.warning(
            "The web interface listens on %s: everybody who can reach that address can drive the agent.",
            host,
        )
    print(f"coder web: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
