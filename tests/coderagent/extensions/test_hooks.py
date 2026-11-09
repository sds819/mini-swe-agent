"""Hooks: user defined commands that run at the important moments of a session."""

import json
import sys

from coderagent.config.schema import HookCommand, HookConfig, HookMatcher
from coderagent.core.events import EventBus, EventType
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.extensions.hooks import HookResult, HookRunner, merge_results
from coderagent.models.gateway import ModelGateway
from coderagent.testing.factory import build_executor
from coderagent.testing.scripted_model import ScriptedModel


def _script(tmp_path, source: str) -> str:
    """A hook command that runs the given python source."""
    path = tmp_path / "hook.py"
    path.write_text(source, encoding="utf-8")
    return f"{sys.executable} {path}"


def _runner(tmp_path, event: str, source: str, matcher: str = "", **kwargs) -> HookRunner:
    return HookRunner(
        HookConfig(
            events={
                event: [HookMatcher(matcher=matcher, hooks=[HookCommand(command=_script(tmp_path, source), **kwargs)])]
            }
        ),
        tmp_path,
    )


def _loop(tmp_path, responses, hooks=None):
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    model = ScriptedModel(responses)
    executor = build_executor(tmp_path, hooks=hooks)
    loop = AgentLoop(
        ModelGateway(model),
        executor,
        session,
        store,
        EventBus(),
        tools=executor.registry.schemas(),
        hooks=hooks,
    )
    return loop, model


def _assistant(content: str = "", tool_calls: list[dict] | None = None) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or [], "extra": {"cost": 0.0}}


def _write_call(path: str, content: str = "new") -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": "write", "arguments": json.dumps({"path": path, "content": content})},
    }


def test_a_hook_can_deny_a_tool(tmp_path):
    hooks = _runner(tmp_path, "PreToolUse", "import json\nprint(json.dumps({'decision': 'deny', 'reason': 'nope'}))")
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "nope" in observations[0]["content"]
    assert not (tmp_path / "a.py").exists()


def test_a_hook_can_rewrite_the_arguments(tmp_path):
    hooks = _runner(
        tmp_path,
        "PreToolUse",
        "import json\nprint(json.dumps({'updatedInput': {'path': 'other.py', 'content': 'rewritten'}}))",
    )
    executor = build_executor(tmp_path, hooks=hooks)
    executor.execute(executor.plan([_write_call("a.py")]))
    assert not (tmp_path / "a.py").exists()
    assert (tmp_path / "other.py").read_text(encoding="utf-8") == "rewritten"


def test_the_rewritten_arguments_are_the_ones_that_are_approved(tmp_path):
    """The permission check sees the arguments of the hook, not the ones of the model."""
    from coderagent.tools.permissions import PermissionMode

    hooks = _runner(
        tmp_path,
        "PreToolUse",
        "import json\nprint(json.dumps({'updatedInput': {'path': 'safe.py', 'content': 'x'}}))",
    )
    executor = build_executor(tmp_path, mode=PermissionMode.DEFAULT, hooks=hooks)
    executor.execute(executor.plan([_write_call("secret.py")]))
    assert not (tmp_path / "secret.py").exists()


def test_the_matcher_selects_the_tools(tmp_path):
    hooks = _runner(
        tmp_path,
        "PreToolUse",
        "import json\nprint(json.dumps({'decision': 'deny', 'reason': 'no writes'}))",
        matcher="write|edit",
    )
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "no writes" in observations[0]["content"]


def test_a_hook_that_fails_is_ignored(tmp_path):
    hooks = _runner(tmp_path, "PreToolUse", "import sys\nsys.exit(3)")
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "Error" not in observations[0]["content"]
    assert (tmp_path / "a.py").exists()


def test_a_failing_hook_blocks_when_it_is_strict(tmp_path):
    hooks = _runner(tmp_path, "PreToolUse", "import sys\nsys.exit(3)", strict=True)
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "blocked" in observations[0]["content"]
    assert not (tmp_path / "a.py").exists()


def test_output_that_is_not_json_is_ignored(tmp_path):
    hooks = _runner(tmp_path, "PreToolUse", "print('not json at all')")
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "Error" not in observations[0]["content"]


def test_a_hook_that_never_ends_is_ignored(tmp_path):
    hooks = _runner(tmp_path, "PreToolUse", "import time\ntime.sleep(5)", timeout=1)
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "Error" not in observations[0]["content"]


def test_the_post_tool_hook_adds_context(tmp_path):
    hooks = _runner(tmp_path, "PostToolUse", "import json\nprint(json.dumps({'additionalContext': 'lint it'}))")
    executor = build_executor(tmp_path, hooks=hooks)
    observations = executor.execute(executor.plan([_write_call("a.py")]))
    assert "lint it" in observations[0]["content"]


def test_the_prompt_hook_can_block_the_prompt(tmp_path):
    hooks = _runner(
        tmp_path, "UserPromptSubmit", "import json\nprint(json.dumps({'decision': 'block', 'reason': 'no'}))"
    )
    loop, model = _loop(tmp_path, [_assistant("never used")], hooks=hooks)
    result = loop.run_turn("do something")
    assert result.stop_reason == "error"
    assert "no" in result.error
    assert model.calls == []


def test_the_prompt_hook_can_add_context(tmp_path):
    hooks = _runner(
        tmp_path, "UserPromptSubmit", "import json\nprint(json.dumps({'additionalContext': 'the answer is 42'}))"
    )
    loop, model = _loop(tmp_path, [_assistant("done")], hooks=hooks)
    loop.run_turn("what is the answer")
    assert "the answer is 42" in model.calls[0][-1]["content"]


def test_the_prompt_hook_can_rewrite_the_prompt(tmp_path):
    hooks = _runner(
        tmp_path,
        "UserPromptSubmit",
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "print(json.dumps({'updatedInput': data['prompt'] + ' (in English)'}))",
    )
    loop, model = _loop(tmp_path, [_assistant("done")], hooks=hooks)
    loop.run_turn("translate this")
    assert model.calls[0][-1]["content"] == "translate this (in English)"


def test_the_rewritten_prompt_is_what_the_model_sees_and_the_log_keeps_both(tmp_path):
    """The log keeps the prompt the model saw, so a replay says the same thing."""
    hooks = _runner(
        tmp_path, "UserPromptSubmit", "import json\nprint(json.dumps({'updatedInput': 'the rewritten prompt'}))"
    )
    loop, model = _loop(tmp_path, [_assistant("done")], hooks=hooks)
    loop.run_turn("what the user typed")
    events = loop.store.events(loop.session.id)
    message = next(event for event in events if event.type == EventType.USER_MESSAGE)
    assert message.payload["content"] == "the rewritten prompt"
    assert message.payload["original"] == "what the user typed"


def test_the_context_of_the_hook_goes_to_the_rewritten_prompt(tmp_path):
    hooks = _runner(
        tmp_path,
        "UserPromptSubmit",
        "import json\n"
        "print(json.dumps({'updatedInput': 'the rewritten prompt', 'additionalContext': 'and this'}))",
    )
    loop, model = _loop(tmp_path, [_assistant("done")], hooks=hooks)
    loop.run_turn("what the user typed")
    content = model.calls[0][-1]["content"]
    assert content.startswith("the rewritten prompt")
    assert "and this" in content


def test_a_prompt_is_not_the_arguments_of_a_tool(tmp_path):
    """A string `updatedInput` of a tool hook does not replace the arguments."""
    hooks = _runner(
        tmp_path, "PreToolUse", "import json\nprint(json.dumps({'updatedInput': 'not arguments'}))"
    )
    executor = build_executor(tmp_path, hooks=hooks)
    executor.execute(executor.plan([_write_call("a.py")]))
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "new"


def test_the_stop_hook_keeps_the_agent_going(tmp_path):
    hooks = _runner(
        tmp_path,
        "Stop",
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "if data.get('last_message') == 'half':\n"
        "    print(json.dumps({'decision': 'block', 'reason': 'not yet'}))",
    )
    loop, model = _loop(tmp_path, [_assistant("half"), _assistant("really done")], hooks=hooks)
    loop.run_turn("go")
    assert len(model.calls) == 2
    assert "not yet" in model.calls[1][-1]["content"]


def test_the_session_hooks_run(tmp_path):
    hooks = _runner(tmp_path, "SessionStart", "import json\nprint(json.dumps({'additionalContext': 'hello'}))")
    loop, _ = _loop(tmp_path, [_assistant("done")], hooks=hooks)
    assert hooks.apply("SessionStart", {"session_id": loop.session.id}).additional_context == "hello"


def test_the_results_are_merged():
    merged = merge_results(
        [
            HookResult(decision="allow", additional_context="one"),
            HookResult(decision="deny", reason="no", additional_context="two"),
            HookResult(updated_input={"path": "b.py"}),
        ]
    )
    assert merged.decision == "deny"
    assert merged.reason == "no"
    assert merged.additional_context == "one\ntwo"
    assert merged.updated_input == {"path": "b.py"}
