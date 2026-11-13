"""The `task` tool: a job that runs in its own context."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from coderagent.config.schema import HookCommand, HookConfig, HookMatcher
from coderagent.core.events import EventType
from coderagent.core.session import SessionStore
from coderagent.core.subagent import (
    SubAgentRunner,
    SubagentSpec,
    load_subagents,
    parse_subagent,
)
from coderagent.extensions.hooks import HookRunner
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_context
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.tools.builtin import build_registry
from coderagent.tools.builtin.task import TaskTool
from coderagent.tools.permissions import PermissionMode, PermissionPolicy

SPEC = """---
name: finder
description: Finds the thing.
tools: [read, grep]
model_purpose: cheap
max_turns: 3
---
You are the finder. Look and report.
"""


def _spec(**kwargs) -> SubagentSpec:
    defaults = {
        "name": "finder",
        "description": "Finds the thing.",
        "system_prompt": "You are the finder.",
        "tools": ["read", "grep"],
        "model_purpose": "cheap",
        "max_turns": 3,
    }
    return SubagentSpec(**{**defaults, **kwargs})


def _runner(model, tmp_path, **kwargs):
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path))
    return SubAgentRunner(
        ModelGateway(model),
        build_registry(),
        policy,
        lambda: build_context(tmp_path, policy=policy),
        **kwargs,
    )


def _call(name: str, arguments: dict, call_id: str = "c1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_the_definition_file_is_read(tmp_path):
    path = tmp_path / "finder.md"
    path.write_text(SPEC, encoding="utf-8")
    spec = parse_subagent(path)
    assert spec.name == "finder"
    assert spec.tools == ["read", "grep"]
    assert spec.model_purpose == "cheap"
    assert spec.max_turns == 3
    assert spec.system_prompt == "You are the finder. Look and report."


def test_a_file_without_front_matter_is_ignored(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text("Just text.", encoding="utf-8")
    assert parse_subagent(path) is None


def test_the_builtin_sub_agents_are_always_there(tmp_path):
    specs = load_subagents(tmp_path)
    assert "code-explorer" in specs
    assert "verifier" in specs
    assert "refactorer" in specs
    assert specs["code-explorer"].tools == ["read", "grep", "glob", "ls"]


def test_a_project_sub_agent_wins_over_a_builtin_one(tmp_path):
    directory = tmp_path / ".coderagent" / "agents"
    directory.mkdir(parents=True)
    (directory / "verifier.md").write_text(
        "---\nname: verifier\ndescription: Mine.\ntools: [read]\n---\nDo it my way.", encoding="utf-8"
    )
    specs = load_subagents(tmp_path)
    assert specs["verifier"].description == "Mine."
    assert specs["verifier"].system_prompt == "Do it my way."


def test_the_sub_agent_does_not_see_the_conversation_of_the_main_agent(tmp_path):
    model = ScriptedModel([{"role": "assistant", "content": "Found it."}])
    result = _runner(model, tmp_path).run(_spec(), "Find the thing", "Look in src/")
    assert result["status"] == "completed"
    assert result["summary"] == "Found it."
    assert model.calls[0][0]["role"] == "system"
    assert "Find the thing" in model.calls[0][1]["content"]


def test_the_white_list_of_the_tools_is_enforced(tmp_path):
    """The sub agent cannot call a tool that is not on its list."""
    target = tmp_path / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("bash", {"command": "cat secret.txt"})],
            },
            {"role": "assistant", "content": "I could not read it."},
        ]
    )
    result = _runner(model, tmp_path).run(_spec(tools=["read"]), "Find", "Look")
    assert result["summary"] == "I could not read it."
    assert "secret" not in json.dumps(result)


def test_the_result_is_structured(tmp_path):
    model = ScriptedModel([{"role": "assistant", "content": "- first finding\n- second finding"}])
    result = _runner(model, tmp_path).run(_spec(), "Find", "Look")
    assert result["findings"] == ["first finding", "second finding"]
    assert result["status"] == "completed"
    assert result["turns"] == 1
    assert result["cost"] == 0.0


def test_the_files_the_sub_agent_changed_are_reported(tmp_path):
    """Reading a file is not touching it. Only the changes are reported."""
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("read", {"path": "a.py"})],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("edit", {"path": "b.py", "old_string": "x", "new_string": "y"})],
            },
            {"role": "assistant", "content": "Changed it."},
        ]
    )
    result = _runner(model, tmp_path).run(_spec(tools=["read", "edit"]), "Find", "Look")
    assert result["files_touched"] == ["b.py"]


def test_the_sub_agent_stops_at_the_turn_limit(tmp_path):
    model = ScriptedModel(
        [{"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]} for _ in range(5)]
    )
    result = _runner(model, tmp_path).run(_spec(max_turns=2), "Find", "Look")
    assert result["status"] == "max_turns"
    assert result["turns"] == 2


def test_the_ceiling_of_the_configuration_holds_the_sub_agent_down(tmp_path):
    """The configuration may say: no sub agent runs longer than this."""
    model = ScriptedModel(
        [{"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]} for _ in range(5)]
    )
    result = _runner(model, tmp_path, max_turns=2).run(_spec(max_turns=10), "Find", "Look")
    assert result["status"] == "max_turns"
    assert result["turns"] == 2


def test_a_sub_agent_may_use_fewer_turns_than_the_ceiling(tmp_path):
    model = ScriptedModel(
        [{"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]} for _ in range(5)]
    )
    result = _runner(model, tmp_path, max_turns=10).run(_spec(max_turns=2), "Find", "Look")
    assert result["status"] == "max_turns"
    assert result["turns"] == 2


def test_without_a_ceiling_the_sub_agent_keeps_its_own_limit(tmp_path):
    model = ScriptedModel(
        [{"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]} for _ in range(5)]
    )
    result = _runner(model, tmp_path).run(_spec(max_turns=2), "Find", "Look")
    assert result["turns"] == 2


def test_a_sub_agent_without_a_limit_keeps_going(tmp_path):
    """`max_turns: 0` means no limit, like it does everywhere else."""
    model = ScriptedModel(
        [
            {"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]},
            {"role": "assistant", "content": "", "tool_calls": [_call("read", {"path": "a.py"})]},
            {"role": "assistant", "content": "Found it."},
        ]
    )
    result = _runner(model, tmp_path).run(_spec(max_turns=0), "Find", "Look")
    assert result["status"] == "completed"
    assert result["turns"] == 3


def _peak_parallelism(tmp_path, **kwargs) -> int:
    """How many sub agents ran at the same time at the most."""
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow(messages):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return {"role": "assistant", "content": "Done."}

    runner = _runner(ScriptedModel(side_effect=slow), tmp_path, **kwargs)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runner.run(_spec(), "Find", "Look"), range(4)))
    assert [result["status"] for result in results] == ["completed"] * 4
    return peak


def test_only_a_few_sub_agents_run_at_the_same_time(tmp_path):
    """The provider is not flooded with sub agents that all run at once."""
    assert _peak_parallelism(tmp_path, max_parallel=2) == 2


def test_without_a_limit_the_sub_agents_run_at_the_same_time(tmp_path):
    assert _peak_parallelism(tmp_path) == 4


def test_the_cost_of_the_sub_agent_is_added_to_the_main_one(tmp_path):
    model = ScriptedModel([{"role": "assistant", "content": "Done."}])
    gateway = ModelGateway(model)
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path))
    runner = SubAgentRunner(
        gateway,
        build_registry(),
        policy,
        lambda: build_context(tmp_path, policy=policy),
        gateway_for=lambda purpose: ModelGateway(
            ScriptedModel([{"role": "assistant", "content": "x", "extra": {"cost": 0.25}}])
        ),
    )
    runner.run(_spec(), "Find", "Look")
    assert gateway.total_cost == 0.25


def test_the_sub_agent_only_pays_for_its_own_calls(tmp_path):
    """The main agent had already spent something when the sub agent starts."""
    model = ScriptedModel([{"role": "assistant", "content": "Done.", "extra": {"cost": 0.25}}])
    gateway = ModelGateway(model)
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path))
    runner = SubAgentRunner(
        gateway,
        build_registry(),
        policy,
        lambda: build_context(tmp_path, policy=policy),
        gateway_for=lambda purpose: gateway,
    )
    result = runner.run(_spec(), "Find", "Look")
    assert result["cost"] == 0.25


def test_the_cost_of_a_second_sub_agent_is_not_counted_twice(tmp_path):
    """The gateway of the purpose is shared, so the second run must only add its own cost."""
    gateway = ModelGateway(
        ScriptedModel(
            [
                {"role": "assistant", "content": "Done.", "extra": {"cost": 0.25}},
                {"role": "assistant", "content": "Done.", "extra": {"cost": 0.25}},
            ]
        )
    )
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=Path(tmp_path))
    main = ModelGateway(ScriptedModel([{"role": "assistant", "content": "ok"}]))
    runner = SubAgentRunner(
        main,
        build_registry(),
        policy,
        lambda: build_context(tmp_path, policy=policy),
        gateway_for=lambda purpose: gateway,
    )
    runner.run(_spec(), "Find", "Look")
    runner.run(_spec(), "Find", "Look")
    assert main.total_cost == 0.5


def test_a_broken_sub_agent_is_reported_as_an_error(tmp_path):
    model = ScriptedModel(side_effect=lambda messages: (_ for _ in ()).throw(RuntimeError("no model")))
    result = _runner(model, tmp_path).run(_spec(), "Find", "Look")
    assert result["status"] == "error"
    assert "no model" in result["summary"]


def test_the_sub_agent_goes_through_the_hooks(tmp_path):
    """A hook of the session also holds the sub agent."""
    hooks = HookRunner(
        HookConfig(
            events={
                "PreToolUse": [
                    HookMatcher(matcher="write", hooks=[HookCommand(command='echo \'{"decision": "deny"}\'')])
                ]
            }
        ),
        tmp_path,
    )
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("write", {"path": "a.py", "content": "x"})],
            },
            {"role": "assistant", "content": "I could not write."},
        ]
    )
    result = _runner(model, tmp_path, hooks=hooks).run(_spec(tools=["write"]), "Change", "Do it")

    assert result["summary"] == "I could not write."
    assert not (tmp_path / "a.py").exists()


def test_the_sub_agent_takes_a_checkpoint_before_it_writes(tmp_path):
    taken: list[tuple[str, dict]] = []
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("write", {"path": "a.py", "content": "x"})],
            },
            {"role": "assistant", "content": "Written."},
        ]
    )
    _runner(model, tmp_path, before_write=lambda tool, params: taken.append((tool, params))).run(
        _spec(tools=["write"]), "Change", "Do it"
    )

    assert taken == [("write", {"path": "a.py", "content": "x"})]


def test_the_result_of_a_tool_of_the_sub_agent_is_in_the_log(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_call("write", {"path": "a.py", "content": "x"})],
            },
            {"role": "assistant", "content": "Written."},
        ]
    )
    _runner(model, tmp_path, store=store).run(_spec(tools=["write"]), "Change", "Do it")

    results = [event for event in store.events("test") if event.type == EventType.TOOL_RESULT]
    assert [event.payload["tool"] for event in results] == ["write"]


def test_the_tool_reports_an_unknown_sub_agent(tmp_path):
    tool = TaskTool(runner=object(), specs={"finder": _spec()})
    result = tool.run({"subagent_type": "nope", "description": "d", "prompt": "p"}, build_context(tmp_path))
    assert result.is_error
    assert "unknown sub agent 'nope'" in result.content
    assert "finder" in result.content


def test_the_tool_returns_the_result_as_json(tmp_path):
    runner = _runner(ScriptedModel([{"role": "assistant", "content": "Found it."}]), tmp_path)
    tool = TaskTool(runner=runner, specs={"finder": _spec()})
    result = tool.run({"subagent_type": "finder", "description": "Find", "prompt": "Look"}, build_context(tmp_path))
    assert not result.is_error
    assert json.loads(result.content)["summary"] == "Found it."
