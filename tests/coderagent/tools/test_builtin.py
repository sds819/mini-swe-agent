from coderagent.config.schema import BUILTIN_TOOL_NAMES
from coderagent.tools.builtin import TOOL_NAMES, build_registry


def test_the_builtin_registry_honours_enabled_and_disabled():
    registry = build_registry(enabled=["read", "bash"], disabled=["bash"])
    assert registry.names() == ["read"]
    assert build_registry().names()[:2] == ["read", "write"]


def test_every_builtin_tool_declares_a_usable_schema():
    for schema in build_registry().schemas():
        function = schema["function"]
        assert function["name"]
        assert function["description"]
        assert function["parameters"]["type"] == "object"


def test_the_config_knows_every_builtin_tool():
    assert BUILTIN_TOOL_NAMES == TOOL_NAMES
