"""File tools: read, write, edit and multi_edit."""

import difflib
from pathlib import Path
from typing import Any

from coderagent.core.tokens import trim_lines
from coderagent.tools.base import ToolContext, ToolResult, resolve_path

MAX_LINE_LENGTH = 2000
DEFAULT_READ_LIMIT = 2000


def _read_text(path: Path) -> tuple[str, str]:
    """Return (content, error message)."""
    try:
        data = path.read_bytes()
    except IsADirectoryError:
        return "", f"Error: '{path.name}' is a directory. Use `ls` to list it."
    if b"\x00" in data:
        return "", f"Error: '{path.name}' is a binary file."
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return "", f"Error: '{path.name}' is a binary file."


def _write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(content)


def _apply_edit(content: str, path: str, old_string: str, new_string: str, replace_all: bool) -> tuple[str, int, str]:
    """Replace `old_string` with `new_string`. Returns (content, replacements, error)."""
    old_variants = [old_string]
    new_variants = [new_string]
    if "\r\n" in content and "\r\n" not in old_string:
        old_variants.append(old_string.replace("\n", "\r\n"))
        new_variants.append(new_string.replace("\n", "\r\n"))
    for old_variant, new_variant in zip(old_variants, new_variants):
        count = content.count(old_variant)
        if count == 0:
            continue
        if count > 1 and not replace_all:
            lines = [str(i + 1) for i, line in enumerate(content.splitlines()) if old_variant in line]
            return (
                content,
                0,
                f"Error: old_string is not unique in {path}: it appears {count} times (lines {', '.join(lines)}). "
                "Include more surrounding context to make it unique, or set replace_all=true.",
            )
        return content.replace(old_variant, new_variant, -1 if replace_all else 1), count, ""
    return (
        content,
        0,
        f"Error: old_string not found in {path}. Use `read` to see the exact content, then retry with more context.",
    )


def _unified_diff(old: str, new: str, path: str) -> str:
    return "\n".join(
        difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
    )


class ReadTool:
    name = "read"
    description = "Read a file from the filesystem. Returns the content with line numbers."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the working directory."},
            "offset": {"type": "integer", "description": "First line to read, 1-based. Defaults to 1."},
            "limit": {"type": "integer", "description": "Maximum number of lines to read. Defaults to 2000."},
        },
        "required": ["path"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = params.get("path")
        if not isinstance(path, str) or not path:
            return ToolResult("Error: `path` is required and must be a string.", is_error=True)
        target = resolve_path(ctx, path)
        if not target.exists():
            return ToolResult(
                f"Error: file not found: {path}. Use `ls` to see what is in that directory.",
                is_error=True,
            )
        content, error = _read_text(target)
        if error:
            return ToolResult(error, is_error=True)

        lines = content.splitlines()
        offset = max(1, int(params.get("offset") or 1))
        limit = max(1, int(params.get("limit") or DEFAULT_READ_LIMIT))
        selected = lines[offset - 1 : offset - 1 + limit]
        truncated, info = trim_lines(selected, ctx.config.max_output_tokens)
        head = info.get("head_lines", len(truncated))
        if info:
            tail_start = offset + info["end_line"] - 1
            numbered = (
                [(offset + index, line) for index, line in enumerate(truncated[:head])]
                + [(0, truncated[head])]
                + [(tail_start + index, line) for index, line in enumerate(truncated[head + 1 :])]
            )
        else:
            numbered = [(offset + index, line) for index, line in enumerate(truncated)]
        width = len(str(max((number for number, _ in numbered), default=0)))
        rendered = []
        for number, line in numbered:
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + "... [line truncated]"
            rendered.append(f"{number:>{width}}\t{line}" if number else line)
        output = "\n".join(rendered)
        last = offset + len(selected) - 1
        if last < len(lines):
            if info:
                output += f"\n... ({len(lines)} lines in the file, use offset={last + 1} to continue)"
            else:
                output += f"\n... (showing lines {offset}-{last} of {len(lines)}, use offset={last + 1} to continue)"
        metadata: dict[str, Any] = {"path": str(target), "lines": len(lines)}
        if info:
            metadata["truncated"] = {
                "path": path,
                "start_line": offset + info["start_line"] - 1,
                "end_line": offset + info["end_line"] - 1,
                "elided_lines": info["elided_lines"],
            }
        return ToolResult(output, metadata=metadata)


class WriteTool:
    name = "write"
    description = "Write a file, creating it if needed. Overwrites existing content."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the working directory."},
            "content": {"type": "string", "description": "The full content of the file."},
        },
        "required": ["path", "content"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = params.get("path")
        content = params.get("content")
        if not isinstance(path, str) or not path:
            return ToolResult("Error: `path` is required and must be a string.", is_error=True)
        if not isinstance(content, str):
            return ToolResult("Error: `content` is required and must be a string.", is_error=True)
        target = resolve_path(ctx, path)
        existed = target.exists()
        old_content = None
        if existed:
            old_content, error = _read_text(target)
            if error:
                return ToolResult(error, is_error=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_text(target, content)
        lines = len(content.splitlines())
        return ToolResult(
            f"{'Updated' if existed else 'Created'} {path} ({lines} lines)",
            metadata={"path": str(target), "old_content": old_content, "created": not existed},
        )


class EditTool:
    name = "edit"
    description = (
        "Replace an exact string in a file. `old_string` must appear exactly once unless `replace_all` is true."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the working directory."},
            "old_string": {"type": "string", "description": "The exact text to replace."},
            "new_string": {"type": "string", "description": "The text to replace it with."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence. Defaults to false."},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = params.get("path")
        old_string = params.get("old_string")
        new_string = params.get("new_string")
        if not isinstance(path, str) or not path:
            return ToolResult("Error: `path` is required and must be a string.", is_error=True)
        if not isinstance(old_string, str) or not old_string:
            return ToolResult("Error: `old_string` is required and must be a non-empty string.", is_error=True)
        if not isinstance(new_string, str):
            return ToolResult("Error: `new_string` is required and must be a string.", is_error=True)

        target = resolve_path(ctx, path)
        if not target.exists():
            return ToolResult(f"Error: file not found: {path}.", is_error=True)
        content, error = _read_text(target)
        if error:
            return ToolResult(error, is_error=True)

        replace_all = bool(params.get("replace_all"))
        new_content, replacements, error = _apply_edit(content, path, old_string, new_string, replace_all)
        if error:
            return ToolResult(error, is_error=True)
        _write_text(target, new_content)
        return ToolResult(
            f"Replaced {replacements} occurrence(s) in {path}",
            metadata={"path": str(target), "diff": _unified_diff(content, new_content, path), "old_content": content},
        )


class MultiEditTool:
    name = "multi_edit"
    description = "Apply several edits to one file. Either all of them are applied or none of them."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the working directory."},
            "edits": {
                "type": "array",
                "description": "Edits to apply in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean"},
                    },
                    "required": ["old_string", "new_string"],
                },
            },
        },
        "required": ["path", "edits"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = params.get("path")
        edits = params.get("edits")
        if not isinstance(path, str) or not path:
            return ToolResult("Error: `path` is required and must be a string.", is_error=True)
        if not isinstance(edits, list) or not edits:
            return ToolResult("Error: `edits` is required and must be a non-empty array.", is_error=True)

        target = resolve_path(ctx, path)
        if not target.exists():
            return ToolResult(f"Error: file not found: {path}.", is_error=True)
        content, error = _read_text(target)
        if error:
            return ToolResult(error, is_error=True)

        updated = content
        for index, edit in enumerate(edits):
            if not isinstance(edit, dict):
                return ToolResult(f"Error: edit #{index + 1} must be an object.", is_error=True)
            old_string = edit.get("old_string")
            new_string = edit.get("new_string")
            if not isinstance(old_string, str) or not old_string:
                return ToolResult(f"Error: edit #{index + 1} needs a non-empty `old_string`.", is_error=True)
            if not isinstance(new_string, str):
                return ToolResult(f"Error: edit #{index + 1} needs a string `new_string`.", is_error=True)
            updated, _, error = _apply_edit(updated, path, old_string, new_string, bool(edit.get("replace_all")))
            if error:
                return ToolResult(f"Edit #{index + 1} failed, no changes were written. {error}", is_error=True)

        _write_text(target, updated)
        return ToolResult(
            f"Applied {len(edits)} edit(s) to {path}",
            metadata={"path": str(target), "diff": _unified_diff(content, updated, path), "old_content": content},
        )
