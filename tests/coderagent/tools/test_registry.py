import pytest

from coderagent.tools.base import ToolResult
from coderagent.tools.registry import ToolRegistry, estimate_tokens


class _Dummy:
    def __init__(self, name: str, description: str = "dummy") -> None:
        self.name = name
        self.description = description
        self.parameters = {"type": "object", "properties": {}}

    def run(self, params, ctx) -> ToolResult:
        return ToolResult("ok")


def test_schemas_are_openai_compatible():
    schemas = ToolRegistry([_Dummy("alpha"), _Dummy("beta")]).schemas()
    assert schemas == [
        {
            "type": "function",
            "function": {"name": "alpha", "description": "dummy", "parameters": {"type": "object", "properties": {}}},
        },
        {
            "type": "function",
            "function": {"name": "beta", "description": "dummy", "parameters": {"type": "object", "properties": {}}},
        },
    ]


def test_registering_the_same_name_twice_overwrites_it():
    registry = ToolRegistry([_Dummy("alpha"), _Dummy("alpha", "second")])
    assert registry.names() == ["alpha"]
    assert registry.get("alpha").description == "second"
    assert registry.get("missing") is None


def test_budget_trimming_drops_the_first_tools_first():
    registry = ToolRegistry([_Dummy(name) for name in ("bash", "read", "grep", "glob", "write")])
    names = [schema["function"]["name"] for schema in registry.schemas(budget_tokens=0)]
    assert names == ["bash", "read"]


def test_budget_trimming_keeps_the_tools_that_fit():
    registry = ToolRegistry([_Dummy(name) for name in ("bash", "read", "grep")])
    assert len(registry.schemas(budget_tokens=10_000)) == 3


def test_estimate_tokens_grows_with_the_schema_size():
    small = ToolRegistry([_Dummy("a")]).schemas()
    large = ToolRegistry([_Dummy("a"), _Dummy("b", "x" * 500)]).schemas()
    assert estimate_tokens(large) > estimate_tokens(small)


def test_registering_a_tool_with_a_duplicate_name_is_reported(caplog):
    registry = ToolRegistry()
    registry.register(_Dummy("alpha"))
    registry.register(_Dummy("alpha"))
    assert "already registered" in caplog.text


@pytest.mark.parametrize("name", ["bash", "read"])
def test_the_essential_tools_are_never_trimmed(name):
    registry = ToolRegistry([_Dummy(name)])
    assert [schema["function"]["name"] for schema in registry.schemas(budget_tokens=0)] == [name]
