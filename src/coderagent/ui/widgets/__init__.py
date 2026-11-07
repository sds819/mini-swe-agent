"""The widgets of the terminal interface."""

from coderagent.ui.widgets.approval_prompt import ApprovalPrompt, Options
from coderagent.ui.widgets.diff_view import DiffView, make_diff
from coderagent.ui.widgets.message_block import MessageBlock
from coderagent.ui.widgets.status_bar import StatusBar
from coderagent.ui.widgets.todo_panel import TodoPanel
from coderagent.ui.widgets.tool_card import ToolCard

__all__ = [
    "ApprovalPrompt",
    "DiffView",
    "MessageBlock",
    "Options",
    "StatusBar",
    "TodoPanel",
    "ToolCard",
    "make_diff",
]
