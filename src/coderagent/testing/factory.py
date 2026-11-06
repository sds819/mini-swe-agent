"""Builders for tests and scripts: a tool context and executor to run tools in."""

from pathlib import Path

from coderagent.config.schema import ToolConfig
from coderagent.core.events import EventBus
from coderagent.core.session import Session
from coderagent.tools.base import ToolContext
from coderagent.tools.builtin import build_registry
from coderagent.tools.executor import ToolExecutor
from coderagent.tools.permissions import ApprovalDecision, Approver, HeadlessApprover, PermissionMode, PermissionPolicy


class AllowAllApprover:
    """Approves every request."""

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW


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


def build_executor(
    cwd: Path,
    *,
    mode: PermissionMode = PermissionMode.BYPASS,
    approver: Approver | None = None,
    config: ToolConfig | None = None,
    context: ToolContext | None = None,
    rules_home=None,
    hooks=None,
) -> ToolExecutor:
    registry = build_registry(config.enabled if config else None, config.disabled if config else None)
    ctx = context or build_context(cwd, policy=PermissionPolicy(mode, [], cwd=Path(cwd)), config=config)
    return ToolExecutor(
        registry,
        ctx.policy,
        lambda: ctx,
        approver or HeadlessApprover(allow=False),
        rules_home=rules_home,
        hooks=hooks,
    )
