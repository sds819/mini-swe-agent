"""The bar at the top: model, tokens, cost, directory and permission mode."""

from textual.widgets import Static


class StatusBar(Static):
    """One line with the state of the session."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = ""
        self.tokens = 0
        self.window = 0
        self.cost = 0.0
        self.cwd = ""
        self.mode = ""
        self.state = ""

    def update_status(self, **kwargs) -> None:
        """Change what the bar shows and redraw it."""
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.render_bar()

    def render_bar(self) -> None:
        tokens = f"{self.tokens / 1000:.1f}k/{self.window / 1000:.0f}k" if self.window else f"{self.tokens}"
        parts = [part for part in (self.model, tokens, f"${self.cost:.4f}", self.cwd, self.mode, self.state) if part]
        self.update(" | ".join(parts))
