"""Coding agent built on top of mini-swe-agent's reusable primitives.

See `docs/design/coding-agent-architecture.md` for the architecture this package implements.
"""

__version__ = "0.1.0"

from coderagent.core.protocols import ModelBackend, ToolExecutor

__all__ = ["ModelBackend", "ToolExecutor", "__version__"]
