"""The question the agent asks when a tool needs the permission of the user."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from coderagent.ui.widgets.diff_view import DiffView
from coderagent.ui.widgets.tool_card import summarize


def _question(tool: str, params: dict[str, Any], reason: str) -> str:
    summary = summarize(params)
    lines = [f"[bold]Allow '{tool}'?[/bold]"]
    if summary:
        lines.append(f"  {summary}")
    if reason:
        lines.append(f"  [dim]{reason}[/dim]")
    lines.append("  [bold]y[/bold] allow  [bold]n[/bold] deny  [bold]a[/bold] always allow")
    return "\n".join(lines)


class ApprovalPrompt(Vertical):
    """Shows what is about to happen, with the diff when it changes a file."""

    DEFAULT_CSS = """
    ApprovalPrompt {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        border: round $warning;
    }
    """

    def __init__(self, tool: str, params: dict[str, Any], reason: str = "", diff: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool = tool
        self.params = params
        self.reason = reason
        self.diff = diff

    def compose(self) -> ComposeResult:
        yield Static(_question(self.tool, self.params, self.reason), classes="question")
        yield DiffView(self.diff)
