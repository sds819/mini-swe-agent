"""The assembly of the agent: the sub agents are part of it."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore
from coderagent.core.subagent import load_subagents
from coderagent.run import build_loop
from coderagent.testing.scripted_model import ScriptedModel


def _loop(tmp_path, config: Config | None = None):
    store = SessionStore(tmp_path / "sessions")
    return build_loop(
        config or Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=store,
        bus=EventBus(),
    )


def test_the_task_tool_is_part_of_the_agent(tmp_path):
    loop = _loop(tmp_path)
    assert "task" in loop.executor.registry.names()


def test_the_task_tool_can_be_switched_off(tmp_path):
    config = Config()
    config.tools.disabled = ["task"]
    loop = _loop(tmp_path, config)
    assert "task" not in loop.executor.registry.names()


def test_the_sub_agents_are_part_of_the_agent(tmp_path):
    loop = _loop(tmp_path)
    assert set(loop.subagents) >= {"code-explorer", "verifier", "refactorer"}


def test_a_project_sub_agent_is_found(tmp_path):
    directory = Path(tmp_path) / ".coderagent" / "agents"
    directory.mkdir(parents=True)
    (directory / "scout.md").write_text(
        "---\nname: scout\ndescription: Looks around.\ntools: [read]\n---\nLook around.", encoding="utf-8"
    )
    loop = _loop(tmp_path)
    assert "scout" in loop.subagents
    assert loop.subagents["scout"].tools == ["read"]


def test_a_sub_agent_of_the_user_is_found(tmp_path):
    home = Path(tmp_path) / "home"
    directory = home / "agents"
    directory.mkdir(parents=True)
    (directory / "scout.md").write_text(
        "---\nname: scout\ndescription: Looks around.\ntools: [read]\n---\nLook around.", encoding="utf-8"
    )
    loop = build_loop(
        Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
        user_home=home,
    )
    assert "scout" in loop.subagents


def test_the_project_sub_agent_wins_over_the_user_one(tmp_path):
    home = Path(tmp_path) / "home"
    for directory, text in (
        (home / "agents", "from the user"),
        (Path(tmp_path) / ".coderagent" / "agents", "from the project"),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "scout.md").write_text(
            f"---\nname: scout\ndescription: {text}\n---\nLook around.", encoding="utf-8"
        )
    specs = load_subagents(tmp_path, home)
    assert specs["scout"].description == "from the project"


def test_the_index_of_the_sub_agents_goes_into_the_system_prompt(tmp_path):
    loop = _loop(tmp_path)
    assert "code-explorer" in loop.context.system_prompt
    assert "verifier" in loop.context.system_prompt


def test_the_configuration_bounds_the_sub_agents(tmp_path):
    """The ceiling of the turns and the number of slots reach the runner."""
    config = Config()
    config.agent.subagent_max_turns = 5
    config.agent.subagent_max_parallel = 1
    runner = _loop(tmp_path, config).executor.registry.get("task").runner
    assert runner.max_turns == 5
    assert runner.max_parallel == 1


def test_the_sub_agents_run_in_parallel_by_default(tmp_path):
    """Two at a time, so a model that fires four tasks does not flood the provider."""
    runner = _loop(tmp_path).executor.registry.get("task").runner
    assert runner.max_parallel == 2
