from pathlib import Path

from coderagent.config.schema import ToolConfig
from coderagent.core.events import EventBus
from coderagent.core.session import Session
from coderagent.tools.base import ToolContext, ToolResult, resolve_path
from coderagent.tools.permissions import PermissionMode, PermissionPolicy


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=tmp_path,
        session=Session(id="test", cwd=tmp_path, created_at=0.0, updated_at=0.0),
        bus=EventBus(),
        policy=PermissionPolicy(PermissionMode.BYPASS, [], cwd=tmp_path),
        config=ToolConfig(),
    )


def test_tool_result_defaults():
    result = ToolResult("hello")
    assert result.content == "hello"
    assert result.is_error is False
    assert result.metadata == {}


def test_resolve_path_is_relative_to_the_working_directory(tmp_path):
    ctx = _ctx(tmp_path)
    assert resolve_path(ctx, "a/b.py") == tmp_path / "a/b.py"
    assert resolve_path(ctx, "/abs/path") == Path("/abs/path")


def test_the_default_policy_denies_writes_outside_the_working_directory(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.policy.check("read", {"path": "x.py"}) == "allow"
    assert ctx.policy.check("write", {"path": "../escape.py"}) == "deny"


def test_every_context_gets_its_own_background_registry(tmp_path):
    assert _ctx(tmp_path).background == {}
    assert _ctx(tmp_path).background is not _ctx(tmp_path).background
