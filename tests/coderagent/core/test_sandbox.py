"""The sandbox: where the commands of the agent run."""

from coderagent.config.schema import SandboxConfig
from coderagent.core.sandbox import build_environment, describe
from coderagent.testing.factory import build_context
from coderagent.tools.builtin.shell import BashTool, CodingEnvironment


class FakeEnvironment:
    """An environment that remembers what it was asked to run."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict:
        self.commands.append(action.get("command", ""))
        return {"output": "remote output", "returncode": 0, "exception_info": ""}


def test_the_local_sandbox_runs_the_commands_on_this_machine(tmp_path):
    environment = build_environment(SandboxConfig(type="local"), tmp_path)
    assert isinstance(environment, CodingEnvironment)
    assert environment.config.cwd == str(tmp_path)


def test_the_environment_of_the_type_is_used(tmp_path):
    """A dotted path is a way to name any environment of mini-swe-agent."""
    environment = build_environment(SandboxConfig(type="minisweagent.environments.local.LocalEnvironment"), tmp_path)
    assert type(environment).__name__ == "LocalEnvironment"
    assert environment.config.cwd == str(tmp_path)


def test_the_sentinel_of_mini_is_not_used_in_the_remote_sandbox(tmp_path):
    """A coding agent ends a turn when the model says so."""
    environment = build_environment(SandboxConfig(type="minisweagent.environments.local.LocalEnvironment"), tmp_path)
    output = {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nthe answer", "returncode": 0}
    assert environment._check_finished(output) is None


def test_the_environment_is_described(tmp_path):
    assert describe(build_environment(SandboxConfig(type="local"), tmp_path)) == "local"
    assert describe(None) == "local"
    assert describe(None, "swerex_docker") == "swerex_docker"


def test_the_bash_tool_runs_in_the_environment_of_the_context(tmp_path):
    environment = FakeEnvironment()
    context = build_context(tmp_path)
    context.env = environment
    result = BashTool().run({"command": "ls -la"}, context)
    assert environment.commands == ["ls -la"]
    assert result.content == "remote output"
    assert not result.is_error


def test_the_bash_tool_falls_back_to_the_local_machine(tmp_path):
    context = build_context(tmp_path)
    result = BashTool().run({"command": "echo hello"}, context)
    assert "hello" in result.content
    assert not result.is_error


def test_the_agent_runs_the_commands_in_its_sandbox(tmp_path):
    from coderagent.config.schema import Config
    from coderagent.core.events import EventBus
    from coderagent.core.session import SessionStore
    from coderagent.run import build_loop
    from coderagent.testing.scripted_model import ScriptedModel

    config = Config()
    config.sandbox.type = "minisweagent.environments.local.LocalEnvironment"
    loop = build_loop(
        config,
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
    )
    assert type(loop.sandbox).__name__ == "LocalEnvironment"
    assert isinstance(loop.executor.registry.get("bash"), BashTool)


def test_the_sandbox_of_the_agent_is_in_the_tool_context(tmp_path):
    from coderagent.config.schema import Config
    from coderagent.core.events import EventBus
    from coderagent.core.session import SessionStore
    from coderagent.run import build_loop
    from coderagent.testing.scripted_model import ScriptedModel

    loop = build_loop(
        Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
    )
    assert isinstance(loop.executor.ctx_factory().env, CodingEnvironment)
