"""Assembly of the coding agent: config -> model -> environment -> session -> loop."""

import logging
import time
from pathlib import Path

from coderagent.config.schema import Config, ContextConfig
from coderagent.core.budget import context_window_for
from coderagent.core.checkpoint import CheckpointStore, create_file_checkpoint
from coderagent.core.context import ContextEngine
from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.loop import AgentLoop, TurnResult
from coderagent.core.protocols import ModelBackend
from coderagent.core.sandbox import build_environment
from coderagent.core.session import SessionStore
from coderagent.core.subagent import SubAgentRunner, load_subagents
from coderagent.extensions.hooks import HookRunner
from coderagent.extensions.plugins import load as load_plugins
from coderagent.extensions.reflect import (
    PENDING_HEADER,
    Reflection,
    append_facts,
    append_user_preferences,
    parse_reflection,
    pending_path,
    project_memory_path,
    reflect_prompt,
    user_memory_path,
)
from coderagent.extensions.skills import load_skills, skill_index
from coderagent.models.backends import LiteLLMBackend
from coderagent.models.gateway import ModelGateway
from coderagent.models.router import ModelRouter
from coderagent.tools.base import ToolContext
from coderagent.tools.builtin import build_registry
from coderagent.tools.builtin.skill import SkillTool
from coderagent.tools.builtin.task import TaskTool
from coderagent.tools.executor import ToolExecutor
from coderagent.tools.mcp import MCPManager
from coderagent.tools.permissions import HeadlessApprover, PermissionPolicy, Rule
from coderagent.tools.rules import load_rules
from coderagent.ui.commands import register as register_command

logger = logging.getLogger("coderagent.run")


def build_model(config: Config, model_name: str = "") -> ModelBackend:
    return LiteLLMBackend(
        model_name or config.model.model_name,
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


def _context_config(config: Config, model_name: str) -> ContextConfig:
    """The context window follows the model, unless the configuration sets it."""
    if "context_window" in config.context.model_fields_set:
        return config.context
    return config.context.model_copy(update={"context_window": context_window_for(model_name)})


def purpose_gateway(config: Config, gateway: ModelGateway, purpose: str) -> ModelGateway:
    """The gateway of a purpose. The main one when the purpose is not routed."""
    name = ModelRouter(config.model, gateway).resolve(purpose)
    if not name or name == config.model.model_name:
        return gateway
    return ModelGateway(build_model(config, name))


def build_loop(
    config: Config,
    cwd: Path,
    *,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    session=None,
    permission_mode: str | None = None,
    bus: EventBus | None = None,
    approver=None,
    user_home: Path | None = None,
) -> AgentLoop:
    store = store or SessionStore()
    session = session or store.create(cwd)
    policy = build_policy(config, cwd, permission_mode)
    session.permission_mode = policy.mode.value
    bus = bus or EventBus()
    registry = build_registry(config.tools.enabled, config.tools.disabled)
    mcp = MCPManager(config.mcp, bus)
    for tool in mcp.start():
        registry.register(tool)
    extensions, plugins = load_plugins(cwd, user_home)
    for tool in extensions.tools.all():
        registry.register(tool)
    for command in extensions.commands:
        register_command(command)
    for event, matchers in extensions.hooks.events.items():
        config.hooks.events.setdefault(event, []).extend(matchers)
    backend = model if model is not None else build_model(config)
    gateway = ModelGateway(backend)
    router = ModelRouter(config.model, gateway)
    if model is not None:
        """An injected model is the main model, whatever the configuration says."""
        router.main_model = model.get_template_vars().get("model_name", config.model.model_name)
    specs = load_subagents(cwd, user_home)
    skills = load_skills(cwd, user_home)
    environment = build_environment(config.sandbox, cwd)
    system_prompt = config.agent.system_prompt
    if skill_index(skills):
        system_prompt = f"{system_prompt}\n\n{skill_index(skills)}"
    context = ContextEngine(
        session,
        store,
        bus,
        _context_config(config, config.model.model_name),
        gateway,
        system_prompt=system_prompt,
        memory_config=config.memory,
        cwd=cwd,
        summary_model=ModelGateway(build_model(config, config.context.summarize_model))
        if config.context.summarize_model
        else purpose_gateway(config, gateway, "summarize"),
    )
    ctx = ToolContext(cwd=cwd, session=session, bus=bus, policy=policy, config=config.tools, env=environment)
    checkpoints = CheckpointStore(keep=config.checkpoint.keep)
    hooks = HookRunner(config.hooks, cwd) if config.hooks.events else None
    runner = SubAgentRunner(
        gateway,
        registry,
        policy,
        lambda: ctx,
        approver=approver,
        gateway_for=lambda purpose: purpose_gateway(config, gateway, purpose),
        bus=bus,
        session_id=session.id,
    )
    if "task" in config.tools.enabled and "task" not in config.tools.disabled:
        registry.register(TaskTool(runner, specs))
    if "skill" in config.tools.enabled and "skill" not in config.tools.disabled:
        registry.register(SkillTool(skills))

    def before_write(tool: str, params: dict) -> None:
        """Snapshot the file before a write tool changes it."""
        path = params.get("path")
        if path and config.checkpoint.enabled:
            create_file_checkpoint(
                checkpoints, session.id, session.turn_count, cwd, str(path), len(context.history.messages)
            )

    executor = ToolExecutor(
        registry,
        policy,
        lambda: ctx,
        approver or HeadlessApprover(allow=False),
        on_path=context.note_path,
        before_write=before_write,
        hooks=hooks,
    )
    return AgentLoop(
        gateway,
        executor,
        session,
        store,
        bus,
        context=context,
        tools=registry.schemas(),
        system_prompt=system_prompt,
        max_turns=config.agent.max_turns,
        cost_limit=config.agent.cost_limit,
        checkpoints=checkpoints,
        hooks=hooks,
        mcp=mcp,
        subagents=specs,
        router=router,
        plugins=plugins,
        sandbox=environment,
    )


def settle_session(
    loop: AgentLoop, config: Config, cwd: Path, confirm=None, user_home: Path | None = None, gateway=None
) -> Reflection:
    """Ask the model what is worth remembering and write it down.

    The facts about the project are written right away. The preferences of the
    user are only written when `confirm` says so, otherwise they wait.

    The call of the model is a call like any other: it lands in the event log and
    its cost is part of the cost of the session.
    """
    messages = loop.context.history.messages
    if not messages:
        return Reflection()
    gateway = gateway or purpose_gateway(config, loop.model, "reflect")
    before = gateway.total_cost
    message: dict = {}
    try:
        message = gateway.query([{"role": "user", "content": reflect_prompt(messages)}])
    except Exception:
        logger.warning("The reflection of the session failed", exc_info=True)
    cost = gateway.total_cost - before
    if gateway is not loop.model:
        """The reflection ran on its own model, so its cost is booked on the main one."""
        loop.model.total_cost += cost
    reflection = parse_reflection(message.get("content", ""))
    append_facts(project_memory_path(cwd, config.memory), reflection.project_facts, "# Project memory")
    if reflection.user_preferences:
        if confirm is not None and confirm(reflection.user_preferences):
            append_user_preferences(user_memory_path(config.memory, user_home), reflection.user_preferences)
        else:
            append_facts(pending_path(cwd), reflection.user_preferences, PENDING_HEADER)
    _record_reflection(loop, gateway, cost, message, reflection)
    return reflection


def _record_reflection(
    loop: AgentLoop, gateway: ModelGateway, cost: float, message: dict, reflection: Reflection
) -> None:
    """Put the reflection in the event log, so that the money it cost is in the trace."""
    extra = message.get("extra") or {}
    event = Event(
        type=EventType.REFLECTION,
        session_id=loop.session.id,
        timestamp=time.time(),
        payload={
            "cost": cost,
            "purpose": "reflect",
            "model": getattr(gateway.backend, "model_name", ""),
            "tokens_in": int(extra.get("tokens_in") or 0),
            "tokens_out": int(extra.get("tokens_out") or 0),
            "project_facts": reflection.project_facts,
            "user_preferences": reflection.user_preferences,
        },
    )
    loop.bus.publish(event)
    loop.store.append(loop.session.id, event)
    loop.session.total_cost = loop.model.total_cost


def run_turn(
    task: str,
    config: Config,
    *,
    cwd: Path,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    session=None,
    permission_mode: str | None = None,
) -> TurnResult:
    return build_loop(config, cwd, model=model, store=store, session=session, permission_mode=permission_mode).run_turn(
        task
    )
