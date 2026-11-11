"""The configuration of the service."""

import json
from pathlib import Path

CONFIG = json.loads(Path("config.json").read_text())


def timeout() -> int:
    """The seconds before the service gives up."""
    return CONFIG["timeout"]
