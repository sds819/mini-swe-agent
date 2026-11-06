"""Assembly of the coding agent: config -> model -> environment -> session -> loop."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop, TurnResult
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import SessionStore
from coderagent.models.backends import LiteLLMBackend
from coderagent.models.gateway import ModelGateway
from coderagent.tools.base import ToolContext
from coderagent.tools.builtin import build_registry
from coderagent.tools.executor import ToolExecutor
from coderagent.tools.permissions import HeadlessApprover, PermissionPolicy, Rule
from coderagent.tools.rules import load_rules


def build_model(config: Config) -> ModelBackend:
    return LiteLLMBackend(
        config.model.model_name,
        model_kwargs=config.model.model_kwargs,
        set_cache_control=config.model.set_cache_control,
    )


def build_policy(config: Config, cwd: Path, permission_mode: str | None = None) -> PermissionPolicy:
    """Built-in rules, then the project and user rule files, then explicit denies."""
    fields = ("tool", "pattern", "decision", "reason")
    rules = [Rule(**{k: v for k, v in rule.items() if k in fields}) for rule in config.permissions.rules]
    rules += load_rules(cwd)
    rules += [
        Rule(tool="*", pattern=pattern, decision="deny", reason="denied by configuration")
        for pattern in config.permissions.deny_paths
    ]
    return PermissionPolicy(
        permission_mode or config.permissions.mode,
        rules,
        cwd=cwd,
        include_dirs=config.permissions.include_dirs,
    )


def build_loop(
    config: Config,
    cwd: Path,
    *,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    permission_mode: str | None = None,
) -> AgentLoop:
    store = store or SessionStore()
    session = store.create(cwd)
    policy = build_policy(config, cwd, permission_mode)
    session.permission_mode = policy.mode.value
    bus = EventBus()
    registry = build_registry(config.tools.enabled, config.tools.disabled)
    ctx = ToolContext(cwd=cwd, session=session, bus=bus, policy=policy, config=config.tools)
    executor = ToolExecutor(registry, policy, lambda: ctx, HeadlessApprover(allow=False))
    return AgentLoop(
        ModelGateway(model if model is not None else build_model(config)),
        executor,
        session,
        store,
        bus,
        tools=registry.schemas(),
        system_prompt=config.agent.system_prompt,
        max_turns=config.agent.max_turns,
        cost_limit=config.agent.cost_limit,
    )


def run_turn(
    task: str,
    config: Config,
    *,
    cwd: Path,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    permission_mode: str | None = None,
) -> TurnResult:
    return build_loop(config, cwd, model=model, store=store, permission_mode=permission_mode).run_turn(task)
