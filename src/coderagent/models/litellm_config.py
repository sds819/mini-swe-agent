"""The model list of a litellm config file: the aliases of the models."""

from pathlib import Path
from typing import Any

import yaml


def deployments(path: str | Path) -> dict[str, dict[str, Any]]:
    """The model list of the file, keyed by the alias of every entry."""
    if not path:
        return {}
    file = Path(path).expanduser()
    if not file.is_file():
        return {}
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return {
        entry["model_name"]: entry.get("litellm_params") or {}
        for entry in data.get("model_list") or []
        if entry.get("model_name")
    }


def resolve(path: str | Path, model_name: str) -> tuple[str, dict[str, Any]]:
    """The real model and the parameters of an alias.

    The name itself and no parameters when the name is not an alias.
    """
    params = deployments(path).get(model_name)
    if params is None:
        return model_name, {}
    return params.get("model", model_name), {key: value for key, value in params.items() if key != "model"}
