"""Where the coding agent keeps its configuration and session data."""

import os
from pathlib import Path


def config_home() -> Path:
    """Root of the coder agent's user-level data. Overridable via `MSWEA_CODER_HOME`."""
    home = os.getenv("MSWEA_CODER_HOME")
    return Path(home) if home else Path.home() / ".coderagent"
