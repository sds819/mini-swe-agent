"""The question the agent asks when a tool needs the permission of the user."""

from collections.abc import Sequence
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from coderagent.ui.widgets.diff_view import DiffView
from coderagent.ui.widgets.tool_card import summarize

OPTIONS = (("y", "allow"), ("n", "deny"), ("a", "always allow"))
"""The answers, in the order the arrow keys walk through them."""


class Options(Static):
    """The answers of a prompt, one per line.

    Every line is a numbered box: `[*]` when the answer is picked (the star is
    red), `[-]` when it is not (the dash is grey).
    """

    def __init__(self, items: Sequence[tuple[str, str]], *, multi: bool = False, **kwargs) -> None:
        super().__init__("", classes="options", **kwargs)
        self.items = list(items)
        """The answers as (key, label) pairs."""
        self.multi = multi
        """Whether more than one answer can be picked."""
        self.cursor = 0
        """The index of the answer the arrow keys are on."""
        self.selected = {0}
        """The indexes of the answers that are picked."""
        self.update(self.markup())

    def move(self, delta: int) -> None:
        """Move the cursor, wrapping around at the ends."""
        self.cursor = (self.cursor + delta) % len(self.items)
        if not self.multi:
            self.selected = {self.cursor}
        self.update(self.markup())

    def toggle(self, index: int) -> None:
        """Pick an answer, or unpick it when it already is."""
        if self.multi:
            self.selected.symmetric_difference_update({index})
        else:
            self.selected = {index}
            self.cursor = index
        self.update(self.markup())

    @property
    def selected_key(self) -> str:
        """The key of the answer under the cursor."""
        return self.items[self.cursor][0]

    @property
    def selected_keys(self) -> list[str]:
        """The keys of the answers that are picked."""
        return [self.items[index][0] for index in sorted(self.selected)]

    def markup(self) -> str:
        """The answers, one per line, the picked ones with a red star."""
        lines = []
        for index, (key, label) in enumerate(self.items):
            marker = "[red]*[/red]" if index in self.selected else "[gray]-[/gray]"
            number = f"[bold]{index + 1}[/bold]" if index == self.cursor else f"[gray]{index + 1}[/gray]"
            lines.append(f"{number} \\[{marker}] [bold]{key}[/bold] {label}")
        lines.append(f"[dim]{self.hint()}[/dim]")
        return "\n".join(lines)

    def hint(self) -> str:
        """What the keys do."""
        if self.multi:
            return "↑/↓ 移动，空格选中，回车确认"
        return "↑/↓ 移动，回车确认"


class ApprovalPrompt(Vertical):
    """Shows what is about to happen, with the diff when it changes a file.

    The answers can be picked with the arrow keys; the picked one is starred
    in red.
    """

    DEFAULT_CSS = """
    ApprovalPrompt {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        border: round $warning;
    }
    ApprovalPrompt > .options {
        height: auto;
    }
    """

    def __init__(self, tool: str, params: dict[str, Any], reason: str = "", diff: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool = tool
        self.params = params
        self.reason = reason
        self.diff = diff
        self.options = Options(OPTIONS)
        """The answers the user picks from."""

    def compose(self) -> ComposeResult:
        yield Static(self._header(), classes="question")
        yield self.options
        yield DiffView(self.diff)

    def _header(self) -> str:
        lines = [f"[bold]Allow '{self.tool}'?[/bold]"]
        summary = summarize(self.params)
        if summary:
            lines.append(f"  {summary}")
        if self.reason:
            lines.append(f"  [dim]{self.reason}[/dim]")
        return "\n".join(lines)

    def move(self, delta: int) -> None:
        """Move the cursor, wrapping around at the ends."""
        self.options.move(delta)

    @property
    def selected_key(self) -> str:
        """The key of the answer under the cursor."""
        return self.options.selected_key
