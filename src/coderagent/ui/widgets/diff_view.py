"""The diff of a change, with the new lines in green and the old ones in red."""

import difflib
from pathlib import Path

from textual.widgets import Static


def make_diff(before: str, after: str, path: str = "") -> str:
    """The unified diff between two texts."""
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}" if path else "a",
            tofile=f"b/{path}" if path else "b",
            lineterm="",
        )
    )


def diff_of_file(path: Path, before: str) -> str:
    """The diff between what the file was and what it is now."""
    try:
        after = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return make_diff(before, after, path.name)


def prospective_diff(tool: str, params: dict, cwd: Path) -> str:
    """The diff a tool is about to make, before it makes it."""
    path = params.get("path")
    if not isinstance(path, str) or not path:
        return ""
    target = Path(path)
    if not target.is_absolute():
        target = cwd / target
    try:
        before = target.read_text(encoding="utf-8")
    except OSError:
        before = ""
    if tool == "write":
        after = str(params.get("content", ""))
    elif tool == "edit":
        after = before.replace(str(params.get("old_string", "")), str(params.get("new_string", "")), 1)
    elif tool == "multi_edit":
        after = before
        for edit in params.get("edits") or []:
            after = after.replace(str(edit.get("old_string", "")), str(edit.get("new_string", "")), 1)
    else:
        return ""
    return make_diff(before, after, target.name)


def colorize_diff(diff: str) -> str:
    """The diff, with the colors of the lines."""
    lines = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            lines.append(f"[dim]{line}[/dim]")
        elif line.startswith("+"):
            lines.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{line}[/cyan]")
        else:
            lines.append(line)
    return "\n".join(lines)


class DiffView(Static):
    """Shows a diff. Empty when there is nothing to show."""

    DEFAULT_CSS = """
    DiffView {
        height: auto;
    }
    """

    def __init__(self, diff: str = "", **kwargs) -> None:
        super().__init__(colorize_diff(diff), **kwargs)
        self.diff = diff

    def show_diff(self, diff: str) -> None:
        """Show a diff. An empty diff hides the view."""
        self.diff = diff
        self.update(colorize_diff(diff))
        self.display = bool(diff)
