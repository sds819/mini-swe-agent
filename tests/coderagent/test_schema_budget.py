"""The budget of the schemas of the tools: the model only gets what fits."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore
from coderagent.core.subagent import SubAgentRunner, SubagentSpec
from coderagent.models.gateway import ModelGateway
from coderagent.run import build_loop
from coderagent.testing.factory import build_context
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.builtin import build_registry
from coderagent.tools.permissions import PermissionMode, PermissionPolicy


class _Recorder(ScriptedModel):
    """A scripted model that keeps the tools it was given."""

    def __init__(self, responses):
        super().__init__(responses)
        self.tools = None

    def query(self, messages, tools=None, **kwargs):
        self.tools = tools
        return super().query(messages, tools=tools, **kwargs)


def _loop(tmp_path, config: Config | None = None):
    return build_loop(
        config or Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
    )


def test_the_budget_is_a_tenth_of_the_context_window(tmp_path):
    config = Config()
    config.context.context_window = 100_000
    assert _loop(tmp_path, config).schema_budget == 10_000


def test_the_budget_never_goes_below_the_built_in_tools(tmp_path):
    """A small window does not take a tool away from the agent."""
    config = Config()
    config.context.context_window = 1000
    loop = _loop(tmp_path, config)
    assert loop.schema_budget >= len(loop.tools)


def test_the_tools_that_do_not_fit_are_not_given_to_the_model(tmp_path):
    config = Config()
    config.tools.schema_budget_tokens = 100
    loop = _loop(tmp_path, config)
    assert [schema["function"]["name"] for schema in loop.tools] == ["read", "bash"]


def test_the_tools_that_fit_are_all_given_to_the_model(tmp_path):
    loop = _loop(tmp_path)
    assert set(loop.executor.registry.names()) == {schema["function"]["name"] for schema in loop.tools}


def test_the_sub_agent_gets_the_same_budget(tmp_path):
    model = _Recorder([{"role": "assistant", "content": "done"}])
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path))
    runner = SubAgentRunner(
        ModelGateway(model),
        build_registry(),
        policy,
        lambda: build_context(tmp_path, policy=policy),
        schema_budget=100,
    )
    runner.run(
        SubagentSpec(name="finder", tools=["read", "grep", "write"], max_turns=1),
        "Find",
        "Look",
    )
    assert [schema["function"]["name"] for schema in model.tools] == ["read"]
