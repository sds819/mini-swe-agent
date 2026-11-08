"""The model configuration as the browser sees it: merged, layered and without secrets.

The api key is only ever written to the user level configuration file, and it
never leaves the server in clear text.
"""

import os
import time
from pathlib import Path
from typing import Any

import yaml

from coderagent.config.loader import config_layers, load_config
from coderagent.paths import config_home
from coderagent.tools.permissions import PermissionMode

SECRET_MARKERS = ("key", "token", "secret", "password")
"""The names of the settings that never leave the server in clear text."""

PERMISSION_MODES = [mode.value for mode in PermissionMode]
"""The permission modes the browser can choose from."""

PERMISSION_FIELDS = ("mode", "deny_paths", "include_dirs")
"""The permission settings that live directly under `permissions:`."""

DIRECT_FIELDS = ("model_name", "max_retries", "set_cache_control", "routing", "routing_rules")
"""The settings of the model that live directly under `model:`."""

MODEL_FIELDS = (*DIRECT_FIELDS, "api_base", "api_key")
"""The settings the configuration page shows."""


def is_secret(name: str) -> bool:
    return any(marker in name.lower() for marker in SECRET_MARKERS)


def redact(value: Any) -> Any:
    """Everything that looks like a secret is replaced by a mask."""
    if isinstance(value, dict):
        return {key: ("***" if is_secret(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def hint(secret: str) -> str:
    """A hint of a secret: enough to recognize it, too little to use it."""
    if not secret:
        return ""
    return f"********{secret[-4:]}" if len(secret) > 4 else "********"


def _model_of(layer: dict) -> dict:
    model = layer.get("model")
    return model if isinstance(model, dict) else {}


def _defines(layer: dict, field: str) -> bool:
    model = _model_of(layer)
    if field in DIRECT_FIELDS:
        return field in model
    kwargs = model.get("model_kwargs")
    return isinstance(kwargs, dict) and field in kwargs


def sources(cwd: Path) -> dict[str, str]:
    """Which layer every model setting comes from.

    The files win over the environment, the same way the loader merges them.
    """
    layers = config_layers(cwd)
    merged = load_config([], cwd=cwd)
    result = {}
    for field in (*MODEL_FIELDS, *merged.model.model_kwargs):
        source = "defaults"
        for name, layer in layers:
            if _defines(layer, field):
                source = name
        if source == "defaults" and field == "model_name" and os.getenv("MSWEA_MODEL_NAME"):
            source = "env"
        result[field] = source
    return result


def model_view(cwd: Path) -> dict[str, Any]:
    """The model configuration, with the secrets taken out."""
    config = load_config([], cwd=cwd)
    model = config.model
    kwargs = dict(model.model_kwargs)
    api_key = str(kwargs.get("api_key") or "")
    return {
        "model_name": model.model_name,
        "api_base": str(kwargs.get("api_base") or ""),
        "api_key_set": bool(api_key),
        "api_key_hint": hint(api_key),
        "max_retries": model.max_retries,
        "set_cache_control": model.set_cache_control or "",
        "routing": model.routing,
        "routing_rules": [rule.model_dump() for rule in model.routing_rules],
        "model_kwargs": {key: value for key, value in kwargs.items() if not is_secret(key)},
    }


def layers_preview(cwd: Path) -> list[dict[str, Any]]:
    """Every layer, with the secrets taken out."""
    return [{"layer": name, "model": redact(_model_of(layer))} for name, layer in config_layers(cwd)]


def user_config_path() -> Path:
    return config_home() / "config.yaml"


def _permission_of(layer: dict) -> dict:
    permissions = layer.get("permissions")
    return permissions if isinstance(permissions, dict) else {}


def _permission_source(layers: list[tuple[str, dict]], field: str) -> str:
    """The layer the setting comes from, the last one that defines it."""
    source = "defaults"
    for name, layer in layers:
        if field in _permission_of(layer):
            source = name
    return source


def permissions_view(cwd: Path, *, server_mode: str = "") -> dict[str, Any]:
    """The permission settings, as the browser sees them.

    `server_mode` is the mode the server was started with. It wins over the
    files, so it is what the page shows and what the user has to be told about.
    """
    layers = config_layers(cwd)
    permissions = load_config([], cwd=cwd).permissions
    source = {field: _permission_source(layers, field) for field in PERMISSION_FIELDS}
    if server_mode:
        source["mode"] = "server"
    return {
        "mode": server_mode or permissions.mode,
        "modes": list(PERMISSION_MODES),
        "deny_paths": list(permissions.deny_paths),
        "include_dirs": list(permissions.include_dirs),
        "source": source,
        "server_mode": server_mode,
    }


def write_user_permissions(payload: dict) -> Path:
    """Merge the permission settings into the user level configuration file.

    The rules are not touched: they are edited by the approvals of the chat
    page, not here.
    """
    path = user_config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}

    mode = payload.get("mode")
    if isinstance(mode, str) and mode.strip():
        if mode.strip() not in PERMISSION_MODES:
            raise ValueError(f"unknown permission mode '{mode}'")
        permissions["mode"] = mode.strip()
    for field in ("deny_paths", "include_dirs"):
        values = payload.get(field)
        if isinstance(values, list):
            permissions[field] = [str(value).strip() for value in values if str(value).strip()]

    data["permissions"] = permissions
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def write_user_model(payload: dict) -> Path:
    """Merge the model settings into the user level configuration file.

    The project level file is never written: it is in the repository. The
    sections the page does not know about are kept as they are.
    """
    path = user_config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        data = {}
    model = data.get("model")
    if not isinstance(model, dict):
        model = {}
    kwargs = model.get("model_kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}

    name = payload.get("model_name")
    if isinstance(name, str) and name.strip():
        model["model_name"] = name.strip()
    base = payload.get("api_base")
    if isinstance(base, str):
        if base.strip():
            kwargs["api_base"] = base.strip()
        else:
            kwargs.pop("api_base", None)
    key = payload.get("api_key")
    if isinstance(key, str):
        """An empty key removes it, a missing one keeps it."""
        if key.strip():
            kwargs["api_key"] = key.strip()
        else:
            kwargs.pop("api_key", None)
    if payload.get("max_retries") is not None:
        model["max_retries"] = int(payload["max_retries"])
    cache = payload.get("set_cache_control")
    if cache is not None:
        model["set_cache_control"] = cache or None
    routing = payload.get("routing")
    if isinstance(routing, dict):
        model["routing"] = {str(key): str(value) for key, value in routing.items()}
    rules = payload.get("routing_rules")
    if isinstance(rules, list):
        model["routing_rules"] = [rule for rule in rules if isinstance(rule, dict)]
    extra = payload.get("model_kwargs")
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key in ("api_key", "api_base"):
                continue
            kwargs[str(key)] = value

    model["model_kwargs"] = kwargs
    data["model"] = model
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def effective_model(cwd: Path, overrides: dict) -> tuple[str, dict]:
    """The model to talk to and the kwargs to talk with, with the overrides applied."""
    config = load_config([], cwd=cwd)
    kwargs = dict(config.model.model_kwargs)
    name = config.model.model_name
    if isinstance(overrides.get("model_name"), str) and overrides["model_name"].strip():
        name = overrides["model_name"].strip()
    for key in ("api_base", "api_key"):
        value = overrides.get(key)
        if isinstance(value, str):
            if value.strip():
                kwargs[key] = value.strip()
            else:
                kwargs.pop(key, None)
    extra = overrides.get("model_kwargs")
    if isinstance(extra, dict):
        kwargs.update({key: value for key, value in extra.items() if key not in ("api_key", "api_base")})
    return name, kwargs


def test_connection(model_name: str, model_kwargs: dict) -> dict[str, Any]:
    """One cheap call to the model, to see whether the settings work."""
    from coderagent.models.backends import LiteLLMBackend

    backend = LiteLLMBackend(model_name, model_kwargs=model_kwargs)
    previous = os.environ.get("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT")
    os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "1"
    """A wrong key should fail right away, not after ten tries."""
    started = time.time()
    try:
        message = backend.query([{"role": "user", "content": "ping"}], max_tokens=1)
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    finally:
        if previous is None:
            os.environ.pop("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", None)
        else:
            os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = previous
    extra = message.get("extra") or {}
    return {
        "ok": True,
        "content": str(message.get("content", ""))[:200],
        "cost": float(extra.get("cost") or 0.0),
        "latency_ms": int((time.time() - started) * 1000),
    }
