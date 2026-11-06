"""The list of things the agent wants to do."""

from textual.widgets import Static

MARKS = {"completed": "◉", "in_progress": "◐", "pending": "○"}


class TodoPanel(Static):
    """The task list of the agent. Hidden when there is nothing to show."""

    DEFAULT_CSS = """
    TodoPanel {
        height: auto;
        max-height: 8;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.todos: list[dict] = []
        self.display = False

    def show_todos(self, todos: list[dict]) -> None:
        """Show the task list."""
        self.todos = list(todos or [])
        self.display = bool(self.todos)
        self.update(self._text())

    def _text(self) -> str:
        lines = ["Todo"]
        for todo in self.todos:
            mark = MARKS.get(todo.get("status", "pending"), "○")
            lines.append(f"  {mark} {todo.get('content', '')} ({todo.get('status', 'pending')})")
        return "\n".join(lines)
