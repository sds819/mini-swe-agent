"""The built-in slash commands."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.checkpoint import CheckpointStore
from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.core.subagent import load_subagents
from coderagent.models.gateway import ModelGateway
from coderagent.models.router import ModelRouter
from coderagent.testing.factory import build_executor
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.permissions import PermissionMode, PermissionPolicy
from coderagent.ui.commands import COMMANDS, CommandContext, find, load_builtins, run


def _context(tmp_path) -> tuple[CommandContext, list[str]]:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    bus = EventBus()
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        ModelGateway(ScriptedModel([{"role": "assistant", "content": "ok"}])),
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
        subagents=load_subagents(tmp_path),
        router=ModelRouter(Config().model),
    )
    output: list[str] = []
    context = CommandContext(
        loop=loop,
        session=session,
        store=store,
        bus=bus,
        cwd=Path(tmp_path),
        config=Config(),
        policy=PermissionPolicy(PermissionMode.DEFAULT, [], cwd=Path(tmp_path)),
        output=output.append,
    )
    return context, output


def _run(context: CommandContext, output: list[str], line: str) -> str:
    assert run(context, line) is True
    return "\n".join(output)


def test_there_are_enough_commands():
    load_builtins()
    assert len(COMMANDS) >= 18
    assert find("/help") is not None
    assert find("m") is not None
    assert find("nope") is None


def test_a_line_that_is_not_a_command_is_not_a_command(tmp_path):
    context, output = _context(tmp_path)
    assert run(context, "just a message") is False
    assert output == []


def test_an_unknown_command_says_so(tmp_path):
    context, output = _context(tmp_path)
    assert "Unknown command" in _run(context, output, "/nope")


def test_help_lists_the_commands(tmp_path):
    context, output = _context(tmp_path)
    assert "/compact" in _run(context, output, "/help")


def test_help_describes_one_command(tmp_path):
    context, output = _context(tmp_path)
    assert "Compact the conversation" in _run(context, output, "/help compact")


def test_status_shows_the_session(tmp_path):
    context, output = _context(tmp_path)
    assert context.session.id in _run(context, output, "/status")


def test_the_mode_can_be_switched(tmp_path):
    context, output = _context(tmp_path)
    _run(context, output, "/mode plan")
    assert context.policy.mode == PermissionMode.PLAN
    assert context.session.permission_mode == "plan"


def test_an_unknown_mode_is_refused(tmp_path):
    context, output = _context(tmp_path)
    assert "Unknown mode" in _run(context, output, "/mode nope")
    assert context.policy.mode == PermissionMode.DEFAULT


def test_the_plan_command_switches_to_plan(tmp_path):
    context, output = _context(tmp_path)
    _run(context, output, "/plan")
    assert context.policy.mode == PermissionMode.PLAN


def test_the_model_is_shown_and_can_be_switched(tmp_path):
    context, output = _context(tmp_path)
    context.config.model.model_name = "deepseek/deepseek-flash"
    assert "deepseek/deepseek-flash" in _run(context, output, "/model")
    _run(context, output, "/model other/model")
    assert context.config.model.model_name == "other/model"
    assert context.loop.model.backend.model_name == "other/model"


def test_the_model_the_user_picks_wins_over_the_routing(tmp_path):
    context, output = _context(tmp_path)
    _run(context, output, "/model my/model")
    assert context.loop.router.resolve("main", {"tokens": 999999}) == "my/model"


def test_the_todos_are_shown(tmp_path):
    context, output = _context(tmp_path)
    context.session.metadata["todos"] = [{"content": "write the code", "status": "in_progress"}]
    assert "write the code" in _run(context, output, "/todos")


def test_the_cost_is_shown(tmp_path):
    context, output = _context(tmp_path)
    assert "cost so far" in _run(context, output, "/cost")


def test_compact_shrinks_the_context(tmp_path):
    context, output = _context(tmp_path)
    for index in range(30):
        context.loop.context.append({"role": "user", "content": f"question {index}"})
        context.loop.context.append({"role": "assistant", "content": f"answer {index}"})
    assert "Compacted" in _run(context, output, "/compact")
    assert context.loop.context.summary is not None


def test_compact_says_when_there_is_nothing_to_compact(tmp_path):
    context, output = _context(tmp_path)
    assert "Nothing to compact" in _run(context, output, "/compact")


def test_clear_starts_a_new_session(tmp_path):
    context, output = _context(tmp_path)
    before = context.session.id
    _run(context, output, "/clear")
    assert context.session.id != before
    assert context.loop.session.id == context.session.id


def test_resume_lists_the_sessions(tmp_path):
    context, output = _context(tmp_path)
    assert context.session.id in _run(context, output, "/resume")


def test_resume_switches_to_the_session(tmp_path):
    context, output = _context(tmp_path)
    other = context.store.create(tmp_path)
    _run(context, output, f"/resume {other.id}")
    assert context.loop.session.id == other.id


def test_fork_copies_the_session(tmp_path):
    context, output = _context(tmp_path)
    before = context.session.id
    _run(context, output, "/fork")
    assert context.session.id != before
    assert context.loop.session.id == context.session.id
    assert len(context.store.list(tmp_path)) == 2


def test_rewind_lists_the_checkpoints(tmp_path):
    context, output = _context(tmp_path)
    context.checkpoints = CheckpointStore(root=tmp_path / "checkpoints")
    assert "No checkpoints" in _run(context, output, "/rewind")


def test_rewind_says_when_there_are_no_checkpoints_at_all(tmp_path):
    context, output = _context(tmp_path)
    assert "not available" in _run(context, output, "/rewind")


def test_diff_says_when_it_is_not_a_repository(tmp_path):
    context, output = _context(tmp_path)
    assert "Not a git repository" in _run(context, output, "/diff")


def test_init_writes_the_instruction_file(tmp_path):
    context, output = _context(tmp_path)
    _run(context, output, "/init")
    assert "AGENTS.md" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_init_does_not_overwrite_an_existing_file(tmp_path):
    context, output = _context(tmp_path)
    (tmp_path / "AGENTS.md").write_text("mine", encoding="utf-8")
    assert "already exists" in _run(context, output, "/init")
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "mine"


def test_export_writes_the_conversation(tmp_path):
    context, output = _context(tmp_path)
    context.loop.context.append({"role": "user", "content": "hello there"})
    _run(context, output, "/export")
    assert "hello there" in (tmp_path / "conversation.md").read_text(encoding="utf-8")


def test_the_permissions_are_shown(tmp_path):
    context, output = _context(tmp_path)
    assert "mode: default" in _run(context, output, "/permissions")


def test_no_hooks_are_configured(tmp_path):
    context, output = _context(tmp_path)
    assert "No hooks" in _run(context, output, "/hooks")


def test_no_mcp_servers_are_configured(tmp_path):
    context, output = _context(tmp_path)
    assert "No MCP servers" in _run(context, output, "/mcp")


def test_the_context_size_is_shown(tmp_path):
    context, output = _context(tmp_path)
    assert "tokens" in _run(context, output, "/context")


def test_the_sub_agents_are_shown(tmp_path):
    context, output = _context(tmp_path)
    answer = _run(context, output, "/agents")
    assert "code-explorer" in answer
    assert "verifier" in answer
    assert "read, grep" in answer


def test_the_skills_are_shown(tmp_path):
    context, output = _context(tmp_path)
    directory = tmp_path / ".coderagent" / "skills" / "pdf-report"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: pdf-report\ndescription: Make a PDF report.\n---\nMake it.", encoding="utf-8"
    )
    answer = _run(context, output, "/skills")
    assert "pdf-report" in answer
    assert "Make a PDF report." in answer


def test_the_plugins_are_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    context, output = _context(tmp_path)
    directory = tmp_path / ".coderagent" / "plugins" / "hello"
    directory.mkdir(parents=True)
    (directory / "plugin.py").write_text("def register(registry):\n    pass\n", encoding="utf-8")
    answer = _run(context, output, "/plugins")
    assert "hello" in answer
    assert "not trusted" in answer


def test_a_plugin_can_be_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    context, output = _context(tmp_path)
    directory = tmp_path / ".coderagent" / "plugins" / "hello"
    directory.mkdir(parents=True)
    (directory / "plugin.py").write_text("def register(registry):\n    pass\n", encoding="utf-8")
    assert "Trusted" in _run(context, output, "/plugins trust hello")
    assert (tmp_path / "home" / "trusted-plugins.json").exists()


def test_the_memory_is_shown(tmp_path):
    context, output = _context(tmp_path)
    memory = tmp_path / ".coderagent" / "memory"
    memory.mkdir(parents=True)
    (memory / "projects.md").write_text("# Project memory\n\n- the build is make build\n", encoding="utf-8")
    answer = _run(context, output, "/memory")
    assert "the build is make build" in answer
    assert "pending preferences" in answer


def test_a_fact_can_be_forgotten(tmp_path):
    context, output = _context(tmp_path)
    memory = tmp_path / ".coderagent" / "memory"
    memory.mkdir(parents=True)
    (memory / "projects.md").write_text("# Project memory\n\n- the build is make build\n", encoding="utf-8")
    assert "Removed" in _run(context, output, "/memory forget the build is make build")
    assert "make build" not in (memory / "projects.md").read_text(encoding="utf-8")
