"""Plugins: third party extensions of the agent.

A plugin is a directory with a `plugin.py` in it:

    .coderagent/plugins/hello/
    └── plugin.py

    def register(registry):
        registry.tools.register(HelloTool())
        registry.commands.append(Command(name="hello", description="Say hi", handler=hello))

A plugin runs in the process of the agent, without a sandbox, so it is only
loaded when the user has trusted it. The trust list lives in
`~/.coderagent/trusted-plugins.json` and is changed with `/plugins trust`.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coderagent.config.schema import HookConfig
from coderagent.paths import config_home
from coderagent.tools.registry import ToolRegistry
from coderagent.ui.commands import Command

PLUGINS_DIR = Path(".coderagent") / "plugins"
PLUGIN_FILE = "plugin.py"
ENTRY_POINT_GROUP = "coderagent.plugins"
TRUST_FILE = "trusted-plugins.json"
TRUSTED = "trusted"
DENIED = "denied"


@dataclass
class ExtensionRegistry:
    """What a plugin may add to the agent."""

    tools: ToolRegistry = field(default_factory=ToolRegistry)
    commands: list[Command] = field(default_factory=list)
    hooks: HookConfig = field(default_factory=HookConfig)
    model_backends: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plugin:
    """A plugin that was found on the disk."""

    name: str
    register: Callable[[ExtensionRegistry], None]
    path: Path | None = None
    source: str = "directory"


def discover(cwd: Path, user_home: Path | None = None) -> list[Plugin]:
    """The plugins of the project and of the user, plus the installed ones."""
    plugins = []
    for directory in _directories(cwd, user_home):
        for path in sorted(directory.glob(f"*/{PLUGIN_FILE}")):
            plugin = _from_file(path)
            if plugin is not None:
                plugins.append(plugin)
    plugins += _from_entry_points()
    return plugins


def load(
    cwd: Path, user_home: Path | None = None, registry: ExtensionRegistry | None = None, confirm=None
) -> tuple[ExtensionRegistry, list[Plugin]]:
    """Load the trusted plugins.

    A plugin that the user has not answered for yet is only loaded when the
    confirmation says yes, and the answer is remembered. Without a confirmation
    the untrusted plugins are left alone.
    """
    registry = registry if registry is not None else ExtensionRegistry()
    loaded = []
    for plugin in discover(cwd, user_home):
        decision = trust_decision(plugin.name, user_home)
        if decision == DENIED:
            continue
        if decision != TRUSTED:
            if confirm is None or not confirm(plugin):
                if confirm is not None:
                    remember(plugin.name, DENIED, user_home)
                continue
            remember(plugin.name, TRUSTED, user_home)
        plugin.register(registry)
        loaded.append(plugin)
    return registry, loaded


def trust_path(user_home: Path | None = None) -> Path:
    home = Path(user_home) if user_home else config_home()
    return home / TRUST_FILE


def trust_decisions(user_home: Path | None = None) -> dict[str, str]:
    """The plugins the user has already answered for."""
    path = trust_path(user_home)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def trust_decision(name: str, user_home: Path | None = None) -> str:
    return trust_decisions(user_home).get(name, "")


def remember(name: str, decision: str, user_home: Path | None = None) -> Path:
    """Write the answer of the user into the trust list."""
    path = trust_path(user_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    decisions = trust_decisions(user_home)
    decisions[name] = decision
    path.write_text(json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _directories(cwd: Path, user_home: Path | None) -> list[Path]:
    directories = []
    if user_home is not None:
        directories.append(Path(user_home) / PLUGINS_DIR)
    directories.append(Path(cwd) / PLUGINS_DIR)
    return [directory for directory in directories if directory.is_dir()]


def _from_file(path: Path) -> Plugin | None:
    """Read one `plugin.py`. Returns None when it has nothing to register."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"coderagent_plugin_{path.parent.name}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if register is None:
        plugin = getattr(module, "plugin", None)
        register = getattr(plugin, "register", None)
    if not callable(register):
        return None
    return Plugin(name=path.parent.name, register=register, path=path)


def _from_entry_points() -> list[Plugin]:
    from importlib.metadata import entry_points

    plugins = []
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        loaded = entry.load()
        register = getattr(loaded, "register", loaded)
        if callable(register):
            plugins.append(Plugin(name=entry.name, register=register, source="entry-point"))
    return plugins


__all__ = [
    "ENTRY_POINT_GROUP",
    "PLUGINS_DIR",
    "PLUGIN_FILE",
    "ExtensionRegistry",
    "Plugin",
    "discover",
    "load",
    "remember",
    "trust_decision",
    "trust_decisions",
    "trust_path",
]
