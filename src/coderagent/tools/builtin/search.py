"""Search tools: glob, grep and ls.

Implemented in pure Python on purpose: `rg`/`grep` are not guaranteed to exist in
non-interactive shells, and the agent must behave the same everywhere.
"""

import os
import re
from pathlib import Path
from typing import Any

from coderagent.tools.base import ToolContext, ToolResult, resolve_path
from coderagent.tools.permissions import glob_to_regex

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
GLOB_LIMIT = 200
GREP_LIMIT = 100


def _iter_files(root: Path):
    """Yield every file below `root`, skipping ignored directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _is_ignored(path: Path, root: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.relative_to(root).parts[:-1])


class GlobTool:
    name = "glob"
    description = (
        "Find files by pattern. `*` matches within one path segment, `**` crosses directories. "
        "Returns up to 200 paths, sorted."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. `**/*.py`."},
            "path": {"type": "string", "description": "Directory to search in. Defaults to the working directory."},
        },
        "required": ["pattern"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern = params.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult("Error: `pattern` is required and must be a non-empty string.", is_error=True)
        root = resolve_path(ctx, params.get("path") or ".")
        if not root.is_dir():
            return ToolResult(f"Error: not a directory: {params.get('path') or '.'}", is_error=True)

        matcher = glob_to_regex(pattern)
        matches = []
        for path in _iter_files(root):
            relative = path.relative_to(root).as_posix()
            if matcher.match(relative):
                matches.append(relative)
        matches.sort()

        if not matches:
            return ToolResult(f"No files matched '{pattern}' under {root}.")
        truncated = matches[GLOB_LIMIT:]
        matches = matches[:GLOB_LIMIT]
        output = "\n".join(matches)
        if truncated:
            output += f"\n... ({len(truncated)} more matches not shown, narrow the pattern)"
        return ToolResult(output, metadata={"count": len(matches)})


class GrepTool:
    name = "grep"
    description = (
        "Search file contents with a regular expression. "
        "Use `output_mode` to get matching lines, the matching file names, or a per-file count."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for."},
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to the working directory.",
            },
            "glob": {"type": "string", "description": "Only search files matching this glob, e.g. `**/*.py`."},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "What to return. Defaults to `content`.",
            },
            "-i": {"type": "boolean", "description": "Case-insensitive search."},
        },
        "required": ["pattern"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        pattern = params.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult("Error: `pattern` is required and must be a non-empty string.", is_error=True)
        mode = params.get("output_mode", "content")
        if mode not in ("content", "files_with_matches", "count"):
            return ToolResult(
                f"Error: `output_mode` must be one of content, files_with_matches, count (got '{mode}').",
                is_error=True,
            )
        try:
            regex = re.compile(pattern, re.IGNORECASE if params.get("-i") else 0)
        except re.error as error:
            return ToolResult(f"Error: invalid regular expression '{pattern}': {error}", is_error=True)

        root = resolve_path(ctx, params.get("path") or ".")
        if not root.exists():
            return ToolResult(f"Error: path not found: {params.get('path') or '.'}", is_error=True)

        glob_pattern = params.get("glob")
        matcher = glob_to_regex(glob_pattern) if isinstance(glob_pattern, str) and glob_pattern else None
        candidates = [root] if root.is_file() else _iter_files(root)

        lines: list[str] = []
        files: list[str] = []
        counts: list[str] = []
        total = 0
        for path in candidates:
            if root.is_dir() and _is_ignored(path, root):
                continue
            if matcher and not matcher.match(path.name if root.is_file() else path.relative_to(root).as_posix()):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            hits = [line for line in text.splitlines() if regex.search(line)]
            if not hits:
                continue
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            files.append(relative)
            counts.append(f"{relative}:{len(hits)}")
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    total += 1
                    if mode == "content" and len(lines) < GREP_LIMIT:
                        lines.append(f"{relative}:{number}:{line}")

        if mode == "files_with_matches":
            output = "\n".join(files)
        elif mode == "count":
            output = "\n".join(counts)
        else:
            output = "\n".join(lines)
        if not output:
            return ToolResult(f"No matches for '{pattern}'.")
        if mode == "content" and total > len(lines):
            output += f"\n... ({total - len(lines)} more matches not shown, use a more specific pattern)"
        return ToolResult(output, metadata={"matches": total, "files": files})


class LsTool:
    name = "ls"
    description = "List directory entries. `depth` of -1 lists the whole tree recursively."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to list. Defaults to the working directory."},
            "depth": {
                "type": "integer",
                "description": "Recursion depth. 1 (default) lists one level, -1 is unlimited.",
            },
        },
        "required": [],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        target = resolve_path(ctx, params.get("path") or ".")
        if not target.exists():
            return ToolResult(f"Error: path not found: {params.get('path') or '.'}", is_error=True)
        if not target.is_dir():
            return ToolResult(f"Error: not a directory: {params.get('path') or '.'}", is_error=True)

        depth = params.get("depth", 1)
        depth = int(depth) if isinstance(depth, int) else 1
        entries = []
        for dirpath, dirnames, filenames in os.walk(target):
            level = len(Path(dirpath).relative_to(target).parts)
            if depth >= 0 and level >= depth:
                dirnames[:] = []
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
            for name in sorted(dirnames):
                entries.append((Path(dirpath) / name, "d"))
            for name in sorted(filenames):
                entries.append((Path(dirpath) / name, "f"))
        entries.sort()
        if not entries:
            return ToolResult(f"Directory {target} is empty.")
        lines = []
        for path, kind in entries:
            size = "" if kind == "d" else f"{path.stat().st_size:>10}"
            relative = path.relative_to(target).as_posix()
            lines.append(f"{kind} {size}  {relative}")
        return ToolResult("\n".join(lines), metadata={"count": len(entries)})
