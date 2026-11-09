"""The uvicorn entry point of the web interface."""

import logging
import os
import socket
import sys
from pathlib import Path

import litellm

from coderagent.config.loader import load_config
from coderagent.core.protocols import ModelBackend

logger = logging.getLogger("coderagent.web")

LOOPBACK = ("127.0.0.1", "localhost", "::1")
"""The addresses that only the user of the machine can reach."""


def check_address(host: str, port: int) -> None:
    """Make sure the address is free before the server says it is listening.

    A port that is already taken is the most common way for the server to fail,
    and the error of uvicorn does not say what to do about it.
    """
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        """A server that was stopped leaves the port in `TIME_WAIT`: the port is free."""
        try:
            probe.bind((host, port))
        except OSError as error:
            print(
                f"coder web: cannot listen on {host}:{port} ({error.strerror}).\n"
                f"         Another program is using that port. Try another one: --port {port + 1}",
                file=sys.stderr,
            )
            raise SystemExit(1) from error


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
    check_address(host, port)
    print(f"coder web: http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
