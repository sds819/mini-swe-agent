"""Configuration loading: built-in defaults, project file, user file, CLI overrides."""

import os
from pathlib import Path

import yaml

from coderagent.config.schema import Config
from coderagent.paths import config_home
from minisweagent.config import get_config_from_spec
from minisweagent.utils.serialize import recursive_merge

DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
PROJECT_CONFIG = Path(".coderagent") / "config.yaml"
DEFAULT_MODEL_NAME = "anthropic/claude-sonnet-4-5"


def config_layers(cwd: Path | None = None) -> list[tuple[str, dict]]:
    """The configuration layers, from the lowest to the highest priority."""
    layers = [("defaults", yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {})]
    for name, path in (("project", _project_config_path(cwd)), ("user", config_home() / "config.yaml")):
        if path.exists():
            layers.append((name, yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
    return layers


def load_config(specs: list[str] | None = None, cwd: Path | None = None) -> Config:
    """Merge the four configuration layers, later layers win."""
    layers = [data for _, data in config_layers(cwd)]
    layers.extend(get_config_from_spec(spec) for spec in specs or [])
    merged = recursive_merge(*layers)
    model = merged.setdefault("model", {})
    model["model_name"] = model.get("model_name") or os.getenv("MSWEA_MODEL_NAME") or DEFAULT_MODEL_NAME
    return Config(**merged)


def _project_config_path(cwd: Path | None) -> Path:
    return (Path(cwd) if cwd else Path.cwd()) / PROJECT_CONFIG
