"""Builders for tests and scripts: a tool context to run tools in."""

from pathlib import Path

from coderagent.config.schema import ToolConfig
from coderagent.core.events import EventBus
from coderagent.core.session import Session
from coderagent.tools.base import ToolContext
from coderagent.tools.permissions import PermissionMode, PermissionPolicy


def build_context(
    cwd: Path,
    *,
    session: Session | None = None,
    bus: EventBus | None = None,
    policy: PermissionPolicy | None = None,
    config: ToolConfig | None = None,
) -> ToolContext:
    return ToolContext(
        cwd=Path(cwd),
        session=session or Session(id="test", cwd=Path(cwd), created_at=0.0, updated_at=0.0),
        bus=bus or EventBus(),
        policy=policy or PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(cwd)),
        config=config or ToolConfig(),
    )
