"""Settling the experience of a session in the memory.

At the end of a session the model is asked what is worth remembering. Two kinds
of things come out:

- project facts: objective things about this project that are not in the code.
- user preferences: how the user likes to work.

The project facts are written right away. The user preferences are only written
when the user says so: they end up in the instructions of every session, so a
wrong one is expensive.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from coderagent.config.schema import MemoryConfig
from coderagent.paths import config_home

MAX_LINES = 200
"""The project memory does not grow past this. Then it has to be tidied up."""

PROJECT_FILE = "projects.md"
PENDING_FILE = "pending-memory.md"
PENDING_HEADER = "# Preferences waiting for a confirmation"
USER_HEADER = "## Preferences"

REFLECT_PROMPT = """You are looking at a finished session of a coding agent.

Decide what is worth remembering for the sessions that come after it:

- project_facts: objective facts about this project that are not already in the code
  or in the instructions (the build command, the quirks of the tests, where the
  generated files live, ...).
- user_preferences: what the user said about how they like to work (the language
  of the comments, the style of the commits, ...).

Leave a list empty when there is nothing worth remembering. Never repeat what the
instructions already say.

Answer with JSON only, nothing else:
{"project_facts": ["..."], "user_preferences": ["..."]}

The session:
{conversation}
"""


@dataclass
class Reflection:
    """What the model thinks is worth remembering."""

    project_facts: list[str] = field(default_factory=list)
    user_preferences: list[str] = field(default_factory=list)


@dataclass
class MemoryWrite:
    """The outcome of a write to a memory file."""

    written: list[str] = field(default_factory=list)
    warning: str = ""
    """Why nothing was written, when nothing was written."""


def reflect_prompt(messages: list[dict], limit: int = 40) -> str:
    """The prompt that asks the model about the session."""
    return REFLECT_PROMPT.replace("{conversation}", _conversation(messages[-limit:]))


def _conversation(messages: list[dict]) -> str:
    """The messages as text the model can read."""
    lines = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content")
        if not isinstance(content, str):
            calls = message.get("tool_calls") or []
            content = ", ".join((call.get("function") or {}).get("name", "") for call in calls)
        if content:
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def parse_reflection(text: str) -> Reflection:
    """Read the answer of the model. A broken answer gives an empty reflection."""
    payload = _json_of(text)
    if not isinstance(payload, dict):
        return Reflection()
    return Reflection(
        project_facts=_strings(payload.get("project_facts")),
        user_preferences=_strings(payload.get("user_preferences")),
    )


def _json_of(text: str) -> dict | None:
    """The JSON object in the text, with or without the fences around it."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"```$", "", stripped.strip())
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _strings(value) -> list[str]:
    """A list of non empty strings, whatever the model sent."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def project_memory_path(cwd: Path, config: MemoryConfig) -> Path:
    """The file with the facts about this project."""
    return Path(cwd) / config.project_path / PROJECT_FILE


def pending_path(cwd: Path) -> Path:
    """The file with the preferences that wait for a confirmation."""
    return Path(cwd) / ".coderagent" / PENDING_FILE


def user_memory_path(config: MemoryConfig, user_home: Path | None = None) -> Path:
    """The file with the preferences of the user."""
    home = Path(user_home) if user_home else config_home()
    return home / Path(config.user_path).name


def append_facts(path: Path, facts: list[str], header: str) -> MemoryWrite:
    """Append the facts that are not in the file yet. The rest is left alone."""
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    known = {_normalize(line) for line in existing}
    new = []
    for fact in facts:
        fact = fact.strip()
        if not fact or _normalize(fact) in known:
            continue
        known.add(_normalize(fact))
        new.append(fact)
    if not new:
        return MemoryWrite()
    if len(existing) + len(new) + 1 > MAX_LINES:
        return MemoryWrite(warning=f"{path} would grow past {MAX_LINES} lines; tidy it up first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = existing
    if not lines:
        lines = [header, ""]
    elif lines[-1].strip():
        lines.append("")
    lines += [f"- {fact}" for fact in new]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return MemoryWrite(written=new)


def _normalize(text: str) -> str:
    """The text as it is compared, so that a fact is not written twice."""
    return re.sub(r"\W+", " ", text.lower()).strip()


def append_user_preferences(path: Path, preferences: list[str]) -> MemoryWrite:
    """Add the preferences to the instructions of the user, under their own heading."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    known = {_normalize(line) for line in lines}
    new = [item.strip() for item in preferences if item.strip() and _normalize(item) not in known]
    if not new:
        return MemoryWrite()
    if USER_HEADER not in lines:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [USER_HEADER, ""]
    lines += [f"- {item}" for item in new]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return MemoryWrite(written=new)


def read_pending(cwd: Path) -> list[str]:
    """The preferences that wait for a confirmation."""
    path = pending_path(cwd)
    if not path.exists():
        return []
    return [line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def clear_pending(cwd: Path) -> list[str]:
    """Take the pending preferences out of the way and return them."""
    preferences = read_pending(cwd)
    path = pending_path(cwd)
    if path.exists():
        path.unlink()
    return preferences


def forget(path: Path, text: str) -> bool:
    """Remove the line that holds this text. True when something was removed."""
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    wanted = _normalize(text)
    kept = [line for line in lines if _normalize(line) != wanted and not _contains(line, wanted)]
    if len(kept) == len(lines):
        return False
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True


def _contains(line: str, wanted: str) -> bool:
    """True when the line holds the text, with the bullet in front."""
    if not wanted:
        return False
    return wanted in _normalize(line[2:] if line.startswith("- ") else line)


__all__ = [
    "MAX_LINES",
    "MemoryWrite",
    "Reflection",
    "append_facts",
    "append_user_preferences",
    "clear_pending",
    "forget",
    "parse_reflection",
    "pending_path",
    "project_memory_path",
    "read_pending",
    "reflect_prompt",
    "user_memory_path",
]
