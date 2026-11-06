"""A message of the conversation: what the user said, what the agent answered."""

from textual.widgets import Static

ROLE_LABEL = {"user": "You", "assistant": "Agent", "error": "Error"}


class MessageBlock(Static):
    """One message. The reasoning of the agent is shown small and dim."""

    DEFAULT_CSS = """
    MessageBlock {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    """

    def __init__(self, role: str, content: str = "", reasoning: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.role = role
        self.content = content
        self.reasoning = reasoning

    def render(self) -> str:
        lines = [f"[bold]{ROLE_LABEL.get(self.role, self.role)}[/bold]"]
        if self.reasoning:
            lines.append(f"[dim]{self.reasoning}[/dim]")
        if self.content:
            lines.append(self.content)
        return "\n".join(lines)

    def append(self, text: str) -> None:
        """Add text to the message, while it is still arriving."""
        self.content += text
        self.refresh()

    def set_content(self, text: str) -> None:
        self.content = text
        self.refresh()

    def add_reasoning(self, text: str) -> None:
        self.reasoning += text
        self.refresh()
