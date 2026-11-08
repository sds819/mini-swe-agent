"""Browsing the working directory from the browser.

The paths the browser asks for have to stay inside the working directory. The
rules of the user cannot widen that, so the check is done here and not through
the permission policy, which lets an `allow` rule overrule the bounds.
"""

import subprocess
from pathlib import Path
from typing import Any

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.session import Session
from coderagent.tools.base import ToolContext
from coderagent.tools.builtin.fs import ReadTool
from coderagent.tools.builtin.search import list_entries
from coderagent.tools.permissions import PermissionPolicy


class OutsideBounds(ValueError):
    """The path is not in the working directory."""


def policy_for(config: Config, cwd: Path) -> PermissionPolicy:
    """The policy of the boundaries. The rules are not part of it."""
    return PermissionPolicy(
        config.permissions.mode,
        [],
        cwd=cwd,
        include_dirs=config.permissions.include_dirs,
    )


def resolve(cwd: Path, path: str, policy: PermissionPolicy) -> Path:
    """The absolute path of a file of the working directory."""
    target = Path(path or ".")
    resolved = (target if target.is_absolute() else cwd / target).resolve()
    if not policy.within_bounds(str(resolved)):
        raise OutsideBounds(f"'{path}' is outside the working directory {policy.cwd}")
    return resolved


def directory(cwd: Path, path: str, depth: int, policy: PermissionPolicy) -> list[dict[str, Any]]:
    """The entries of a directory, one level or the whole tree."""
    target = resolve(cwd, path, policy)
    if not target.is_dir():
        raise NotADirectoryError(f"'{path}' is not a directory")
    entries = []
    for absolute, kind in list_entries(target, depth):
        entries.append(
            {
                "path": absolute.relative_to(target).as_posix(),
                "name": absolute.name,
                "is_dir": kind == "d",
                "size": absolute.stat().st_size if kind == "f" else 0,
            }
        )
    return entries


def read(cwd: Path, path: str, policy: PermissionPolicy, config: Config) -> dict[str, Any]:
    """The content of a file, with the line numbers the agent gets to see."""
    target = resolve(cwd, path, policy)
    context = ToolContext(
        cwd=cwd,
        session=Session(id="web", cwd=cwd, created_at=0.0, updated_at=0.0),
        bus=EventBus(),
        policy=policy,
        config=config.tools,
    )
    result = ReadTool().run({"path": str(target)}, context)
    return {"path": str(target), "content": result.content, "is_error": result.is_error}


def diff(cwd: Path, path: str, policy: PermissionPolicy) -> str:
    """The changes of the working tree for a path."""
    target = resolve(cwd, path, policy)
    result = subprocess.run(["git", "diff", "--", str(target)], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return result.stderr.strip() or f"git diff failed with code {result.returncode}"
    return result.stdout
