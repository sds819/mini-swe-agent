"""Coding agent built on top of mini-swe-agent's reusable primitives.

See `docs/design/coding-agent-architecture.md` for the architecture this package implements.
"""

import os

__version__ = "0.1.0"

# mini-swe-agent greets the user on import; the coder CLI has its own output.
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")

from coderagent.core.protocols import ModelBackend, ToolExecutor  # noqa: E402

__all__ = ["ModelBackend", "ToolExecutor", "__version__"]
