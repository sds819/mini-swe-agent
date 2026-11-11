"""The plugins: the extensions of the agent that come from outside."""

from pathlib import Path

from coderagent.extensions.plugins import (
    ExtensionRegistry,
    discover,
    load,
    remember,
    trust_decision,
    trust_decisions,
    trust_path,
)

PLUGIN = """
from coderagent.tools.base import ToolResult


class HelloTool:
    name = "hello"
    description = "Say hello."
    parameters = {"type": "object", "properties": {}}

    def run(self, params, ctx):
        return ToolResult("hello")


def register(registry):
    registry.tools.register(HelloTool())
"""


def _write(directory: Path, name: str = "hello", text: str = PLUGIN) -> Path:
    path = directory / name / "plugin.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_plugin_is_found(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    assert [plugin.name for plugin in discover(tmp_path)] == ["hello"]


def test_a_plugin_of_the_user_is_found(tmp_path):
    _write(Path(tmp_path) / "home" / "plugins", name="mine")
    assert [plugin.name for plugin in discover(tmp_path, tmp_path / "home")] == ["mine"]


def test_a_plugin_of_the_user_is_found_without_a_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    _write(Path(tmp_path) / "home" / "plugins", name="mine")
    assert [plugin.name for plugin in discover(tmp_path)] == ["mine"]


def test_an_untrusted_plugin_is_not_loaded(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    registry, loaded = load(tmp_path, tmp_path / "home")
    assert loaded == []
    assert registry.tools.names() == []


def test_a_trusted_plugin_is_loaded(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    remember("hello", "trusted", tmp_path / "home")
    registry, loaded = load(tmp_path, tmp_path / "home")
    assert [plugin.name for plugin in loaded] == ["hello"]
    assert registry.tools.names() == ["hello"]


def test_the_confirmation_loads_the_plugin_and_remembers_it(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    asked: list[str] = []

    def confirm(plugin) -> bool:
        asked.append(plugin.name)
        return True

    registry, loaded = load(tmp_path, tmp_path / "home", confirm=confirm)
    assert asked == ["hello"]
    assert registry.tools.names() == ["hello"]
    assert trust_decision("hello", tmp_path / "home") == "trusted"


def test_a_refused_plugin_is_not_loaded_and_not_asked_again(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    registry, loaded = load(tmp_path, tmp_path / "home", confirm=lambda plugin: False)
    assert loaded == []
    assert registry.tools.names() == []
    assert trust_decision("hello", tmp_path / "home") == "denied"
    assert load(tmp_path, tmp_path / "home", confirm=lambda plugin: True)[1] == []


def test_the_trust_list_is_written_to_the_home(tmp_path):
    path = remember("hello", "trusted", tmp_path / "home")
    assert path == trust_path(tmp_path / "home")
    assert trust_decisions(tmp_path / "home") == {"hello": "trusted"}


def test_a_plugin_without_a_register_function_is_not_used(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins", text="x = 1\n")
    assert discover(tmp_path) == []


def test_a_plugin_may_use_the_object_form(tmp_path):
    _write(
        Path(tmp_path) / ".coderagent" / "plugins",
        text=(
            "class Plugin:\n"
            "    name = 'hello'\n"
            "    def register(self, registry):\n"
            "        registry.model_backends['demo'] = str\n"
            "\n"
            "plugin = Plugin()\n"
        ),
    )
    registry, loaded = load(tmp_path, tmp_path / "home")
    assert loaded == []
    remember("hello", "trusted", tmp_path / "home")
    registry, loaded = load(tmp_path, tmp_path / "home")
    assert registry.model_backends == {"demo": str}


def test_the_code_of_a_plugin_runs_only_when_it_is_trusted(tmp_path):
    marker = tmp_path / "ran.txt"
    _write(
        Path(tmp_path) / ".coderagent" / "plugins",
        text=(f"open({str(marker)!r}, 'w').write('x')\n\ndef register(registry):\n    pass\n"),
    )
    assert [plugin.name for plugin in discover(tmp_path)] == ["hello"]
    assert load(tmp_path, tmp_path / "home")[1] == []
    assert not marker.exists()
    remember("hello", "trusted", tmp_path / "home")
    assert load(tmp_path, tmp_path / "home")[1] != []
    assert marker.exists()


def test_a_plugin_that_does_not_parse_is_not_used(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins", text="def register(registry)\n")
    assert discover(tmp_path) == []


def test_the_registry_starts_empty():
    registry = ExtensionRegistry()
    assert registry.tools.names() == []
    assert registry.commands == []
    assert registry.hooks.events == {}
    assert registry.model_backends == {}


def test_the_tool_of_the_plugin_works(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "plugins")
    remember("hello", "trusted", tmp_path / "home")
    registry, _ = load(tmp_path, tmp_path / "home")
    tool = registry.tools.get("hello")
    assert tool is not None
    assert tool.run({}, None).content == "hello"


def test_the_tool_of_the_plugin_is_part_of_the_agent(tmp_path):
    from coderagent.config.schema import Config
    from coderagent.core.events import EventBus
    from coderagent.core.session import SessionStore
    from coderagent.run import build_loop
    from coderagent.testing.scripted_model import ScriptedModel

    _write(Path(tmp_path) / ".coderagent" / "plugins")
    remember("hello", "trusted", tmp_path / "home")
    loop = build_loop(
        Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
        user_home=tmp_path / "home",
    )
    assert "hello" in loop.executor.registry.names()


def test_an_untrusted_plugin_is_not_part_of_the_agent(tmp_path):
    from coderagent.config.schema import Config
    from coderagent.core.events import EventBus
    from coderagent.core.session import SessionStore
    from coderagent.run import build_loop
    from coderagent.testing.scripted_model import ScriptedModel

    _write(Path(tmp_path) / ".coderagent" / "plugins")
    loop = build_loop(
        Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(tmp_path / "sessions"),
        bus=EventBus(),
        user_home=tmp_path / "home",
    )
    assert "hello" not in loop.executor.registry.names()
