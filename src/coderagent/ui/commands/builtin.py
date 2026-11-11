"""The commands that are always available."""

import json
import subprocess
from pathlib import Path

from coderagent.core.context import ContextEngine
from coderagent.models.backends import LiteLLMBackend
from coderagent.tools.permissions import PermissionMode
from coderagent.ui.commands import COMMANDS, Command, CommandContext, register
from coderagent.ui.commands.compact import compact
from coderagent.ui.commands.resume import fork as fork_session
from coderagent.ui.commands.resume import list_sessions
from coderagent.ui.commands.resume import resume as resume_session
from coderagent.ui.commands.rewind import list_checkpoints, rewind

AGENTS_TEMPLATE = """# {name}

{description}

AGENTS.md is read by the agents at the start of every session, so keep it short
and to the point.

## Layout

{layout}

## Conventions

- Keep the code small and readable; prefer the obvious solution.
- Every change comes with a test.
"""


def _help(context: CommandContext, argument: str) -> None:
    from coderagent.ui.commands import load_builtins

    load_builtins()
    if argument:
        command = next((item for item in COMMANDS if item.name == argument), None)
        context.say(f"/{command.name}: {command.description}" if command else f"No command '/{argument}'.")
        return
    context.say("\n".join(f"/{command.name:<12} {command.description}" for command in COMMANDS))


def _model(context: CommandContext, argument: str) -> None:
    if not argument:
        routing = ", ".join(f"{name} -> {target}" for name, target in context.config.model.routing.items())
        context.say(
            f"model: {context.config.model.model_name}"
            + (f"\nrouting: {routing}" if routing else "\n(no routing configured)")
        )
        return
    context.config.model.model_name = argument
    context.loop.model.backend = LiteLLMBackend(
        argument,
        model_kwargs=context.config.model.model_kwargs,
        litellm_config=context.config.model.litellm_config,
    )
    if context.loop.router is not None:
        context.loop.router.override = argument
    context.say(f"model: {argument}")


def _mode(context: CommandContext, argument: str) -> None:
    if not argument:
        context.say(f"mode: {context.policy.mode.value}")
        return
    try:
        mode = PermissionMode(argument)
    except ValueError:
        context.say(f"Unknown mode '{argument}'. Use one of: {', '.join(item.value for item in PermissionMode)}.")
        return
    context.policy.mode = mode
    context.session.permission_mode = mode.value
    context.say(f"mode: {mode.value}")


def _plan(context: CommandContext, argument: str) -> None:
    context.policy.mode = PermissionMode.PLAN
    context.session.permission_mode = PermissionMode.PLAN.value
    context.say("mode: plan (read only, the agent will not change anything)")


def _compact(context: CommandContext, argument: str) -> None:
    before = context.loop.context.estimated_tokens()
    if not compact(context.loop.context):
        context.say("Nothing to compact yet.")
        return
    context.say(f"Compacted the context: {before} -> {context.loop.context.estimated_tokens()} tokens.")


def _clear(context: CommandContext, argument: str) -> None:
    from coderagent.run import settle

    settle(context.loop, context.config, context.cwd)
    session = context.store.create(context.cwd)
    context.loop.switch_to(session)
    context.session = session
    context.say(f"New session: {session.id}")


def _resume(context: CommandContext, argument: str) -> None:
    if not argument:
        sessions = list_sessions(context.store, context.cwd)
        context.say(
            "\n".join(f"{item.id}  {item.turn_count:>3} turns  {item.cwd}" for item in sessions) or "No sessions yet."
        )
        return
    session = resume_session(context.store, argument)
    context.loop.switch_to(session)
    context.session = session
    context.say(f"Resumed {session.id}")


def _fork(context: CommandContext, argument: str) -> None:
    session_id = argument or context.session.id
    session = fork_session(context.store, session_id)
    context.loop.switch_to(session)
    context.session = session
    context.say(f"Forked {session_id} into {session.id}")


def _rewind(context: CommandContext, argument: str) -> None:
    if context.checkpoints is None:
        context.say("Checkpoints are not available.")
        return
    if not argument:
        checkpoints = list_checkpoints(context.checkpoints, context.session.id)
        context.say(
            "\n".join(f"{item.id}  turn {item.turn}  {sorted(item.payload)}" for item in checkpoints)
            or "No checkpoints yet."
        )
        return
    changed = rewind(context.loop.context, context.checkpoints, argument, context.cwd)
    context.say(f"Restored {len(changed)} file(s): {', '.join(changed) or 'nothing changed'}")


def _diff(context: CommandContext, argument: str) -> None:
    result = subprocess.run(["git", "diff", "--stat"], cwd=context.cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        context.say(f"Not a git repository: {context.cwd}")
        return
    context.say(result.stdout.strip() or "No changes in the working tree.")


def _init(context: CommandContext, argument: str) -> None:
    target = context.cwd / "AGENTS.md"
    if target.exists():
        context.say(f"{target} already exists.")
        return
    entries = sorted(path.name + ("/" if path.is_dir() else "") for path in context.cwd.iterdir())
    target.write_text(
        AGENTS_TEMPLATE.format(
            name=context.cwd.name,
            description=f"Instructions for the agents working on {context.cwd.name}.",
            layout="\n".join(f"- {entry}" for entry in entries[:40]),
        ),
        encoding="utf-8",
    )
    context.say(f"Wrote {target}")


def _cost(context: CommandContext, argument: str) -> None:
    from coderagent.core.telemetry import collect

    loop = context.loop
    metrics = collect(context.store.events(context.session.id))
    context.say(
        f"model: {context.config.model.model_name}\n"
        f"calls: {metrics.model_calls}\n"
        f"tokens in the context: {loop.context.estimated_tokens()}\n"
        f"tokens spent: {loop.session.total_tokens}\n"
        f"cost so far: ${loop.session.total_cost:.4f}\n" + metrics.report()
    )


def _todos(context: CommandContext, argument: str) -> None:
    todos = context.session.metadata.get("todos") or []
    if not todos:
        context.say("No todos.")
        return
    context.say(
        "\n".join(f"[{'x' if todo.get('status') == 'completed' else ' '}] {todo.get('content', '')}" for todo in todos)
    )


def _mcp(context: CommandContext, argument: str) -> None:
    servers = context.config.mcp.servers
    if not servers:
        context.say("No MCP servers configured.")
        return
    status = context.mcp.status() if context.mcp is not None else {}
    context.say(
        "\n".join(
            f"{server.name:<16} {'disabled' if not server.enabled else status.get(server.name, 'not connected')}"
            for server in servers
        )
    )


def _permissions(context: CommandContext, argument: str) -> None:
    rules = context.policy.rules
    lines = [f"mode: {context.policy.mode.value}"]
    lines += [
        f"{rule.tool} {rule.pattern} -> {rule.decision}" + (f" ({rule.reason})" if rule.reason else "")
        for rule in rules
    ]
    context.say("\n".join(lines))


def _hooks(context: CommandContext, argument: str) -> None:
    events = context.config.hooks.events
    if not events:
        context.say("No hooks configured.")
        return
    lines = []
    for name, matchers in events.items():
        for matcher in matchers:
            for hook in matcher.hooks:
                lines.append(f"{name} [{matcher.matcher or '*'}] -> {hook.command}")
    context.say("\n".join(lines))


def _agents(context: CommandContext, argument: str) -> None:
    specs = context.loop.subagents
    if not specs:
        context.say("No sub agents.")
        return
    context.say(
        "\n".join(
            f"{spec.name:<16} {spec.model_purpose:<6} {', '.join(spec.tools)}\n{'':<16} {spec.description}"
            for spec in specs.values()
        )
    )


def _skills(context: CommandContext, argument: str) -> None:
    from coderagent.extensions.skills import load_skills

    skills = load_skills(context.cwd, context.loop.context.user_home)
    if not skills:
        context.say("No skills.")
        return
    context.say(
        "\n".join(f"{skill.name:<16} {skill.description}\n{'':<16} {skill.directory}" for skill in skills.values())
    )


def _plugins(context: CommandContext, argument: str) -> None:
    from coderagent.extensions.plugins import TRUSTED, discover, remember, trust_decision

    plugins = discover(context.cwd, context.loop.context.user_home)
    if argument.startswith("trust "):
        name = argument[len("trust ") :].strip()
        plugin = next((item for item in plugins if item.name == name), None)
        if plugin is None:
            context.say(f"No plugin '{name}'.")
            return
        remember(name, TRUSTED, context.loop.context.user_home)
        context.say(f"Trusted '{name}'. It is loaded the next time the agent starts.")
        return
    if not plugins:
        context.say("No plugins.")
        return
    context.say(
        "\n".join(
            f"{plugin.name:<16} {trust_decision(plugin.name, context.loop.context.user_home) or 'not trusted'}"
            f"  {plugin.source}"
            for plugin in plugins
        )
    )


def _memory(context: CommandContext, argument: str) -> None:
    from coderagent.extensions.reflect import (
        append_user_preferences,
        clear_pending,
        forget,
        pending_path,
        project_memory_path,
        read_pending,
        user_memory_path,
    )

    cwd = context.cwd
    project = project_memory_path(cwd, context.config.memory)
    pending = read_pending(cwd)
    if argument == "confirm":
        preferences = clear_pending(cwd)
        written = append_user_preferences(user_memory_path(context.config.memory), preferences)
        context.say(f"Wrote {len(written.written)} preference(s) to {user_memory_path(context.config.memory)}.")
        return
    if argument.startswith("forget "):
        text = argument[len("forget ") :].strip()
        removed = forget(project, text) or forget(pending_path(cwd), text)
        context.say("Removed." if removed else "Nothing like that in the memory.")
        return
    lines = ["project memory:"]
    lines += [f"  {line}" for line in _lines_of(project)]
    lines.append("pending preferences:")
    lines += [f"  {item}" for item in pending] if pending else ["  none"]
    lines.append("user memory:")
    lines += [f"  {line}" for line in _lines_of(user_memory_path(context.config.memory))]
    context.say("\n".join(lines))


def _lines_of(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _status(context: CommandContext, argument: str) -> None:
    session = context.session
    context.say(
        f"session: {session.id}\n"
        f"state: {session.state.value}\n"
        f"turns: {session.turn_count}\n"
        f"cost: ${session.total_cost:.4f}\n"
        f"cwd: {session.cwd}\n"
        f"mode: {context.policy.mode.value}\n"
        f"sandbox: {context.config.sandbox.type}"
    )


def _sandbox(context: CommandContext, argument: str) -> None:
    """Show where the commands of the agent run."""
    from coderagent.core.sandbox import describe

    sandbox = context.config.sandbox
    lines = [f"type: {sandbox.type}"]
    lines += [f"{key}: {value}" for key, value in (sandbox.model_extra or {}).items()]
    lines.append(f"environment: {describe(context.loop.sandbox, sandbox.type)}")
    context.say("\n".join(lines))


def _export(context: CommandContext, argument: str) -> None:
    target = Path(argument) if argument else context.cwd / "conversation.md"
    lines = ["# Conversation", ""]
    for message in context.loop.context.history.messages:
        role = message.get("role", "")
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        lines += [f"## {role}", "", content, ""]
    target.write_text("\n".join(lines), encoding="utf-8")
    context.say(f"Wrote {target}")


def _context(context: CommandContext, argument: str) -> None:
    engine: ContextEngine = context.loop.context
    context.say(
        f"messages: {len(engine.history.messages)}\n"
        f"tokens: {engine.estimated_tokens()}\n"
        f"summary: {'yes' if engine.summary else 'no'}"
    )


def _exit(context: CommandContext, argument: str) -> None:
    """Leave the interface."""
    if context.quit is None:
        context.say("The server keeps running. Stop it with ctrl+c where it was started.")
        return
    context.quit()


register(Command(name="help", description="List the commands", handler=_help))
register(Command(name="model", description="Show or switch the model", handler=_model, aliases=["m"]))
register(Command(name="mode", description="Show or switch the permission mode", handler=_mode))
register(Command(name="plan", description="Switch to plan mode, where nothing is changed", handler=_plan))
register(Command(name="compact", description="Compact the conversation now", handler=_compact))
register(Command(name="clear", description="Start a new session", handler=_clear))
register(Command(name="resume", description="List the sessions or resume one", handler=_resume))
register(Command(name="fork", description="Copy the session into a new one", handler=_fork))
register(Command(name="rewind", description="Show the checkpoints or roll back to one", handler=_rewind))
register(Command(name="diff", description="Show the changes in the working tree", handler=_diff))
register(Command(name="init", description="Write an AGENTS.md for this project", handler=_init))
register(Command(name="cost", description="Show the tokens and the money spent", handler=_cost))
register(Command(name="todos", description="Show the task list", handler=_todos))
register(Command(name="mcp", description="Show the MCP servers", handler=_mcp))
register(Command(name="permissions", description="Show the rules that are in effect", handler=_permissions))
register(Command(name="hooks", description="Show the hooks that are loaded", handler=_hooks))
register(Command(name="agents", description="Show the sub agents that are available", handler=_agents))
register(Command(name="skills", description="Show the skills that are available", handler=_skills))
register(Command(name="plugins", description="Show the plugins, or trust one of them", handler=_plugins))
register(Command(name="memory", description="Show the memory of the project and of the user", handler=_memory))
register(Command(name="status", description="Show the state of the session", handler=_status))
register(Command(name="sandbox", description="Show where the commands run", handler=_sandbox))
register(Command(name="export", description="Write the conversation to a file", handler=_export))
register(Command(name="context", description="Show the size of the context", handler=_context))
register(Command(name="exit", description="Leave the interface", handler=_exit, aliases=["quit"]))
