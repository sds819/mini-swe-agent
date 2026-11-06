"""The terminal interface.

The core of the agent knows nothing about the screen: it publishes events and the
interface listens to them. The turn itself runs in a thread, so the screen stays
alive while the model is thinking.
"""

import logging
import threading
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input

from coderagent.config.schema import Config
from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.session import SessionStore
from coderagent.run import build_loop
from coderagent.tools.permissions import ApprovalDecision
from coderagent.ui.commands import CommandContext
from coderagent.ui.commands import run as run_command
from coderagent.ui.widgets import ApprovalPrompt, MessageBlock, StatusBar, TodoPanel, ToolCard
from coderagent.ui.widgets.diff_view import prospective_diff

WRITE_TOOLS = {"write", "edit", "multi_edit"}
logger = logging.getLogger("coderagent.ui")


class TUIAprover:
    """Asks the user, through the interface, whether a tool may run."""

    def __init__(self, bus: EventBus, timeout: int = 0) -> None:
        self.bus = bus
        self.timeout = timeout
        self._events: dict[str, threading.Event] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._counter = 0

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        """Wait until the user answers."""
        self._counter += 1
        key = str(self._counter)
        event = threading.Event()
        self._events[key] = event
        self.bus.publish(
            Event(
                type=EventType.APPROVAL_REQUEST,
                session_id="",
                timestamp=time.time(),
                payload={"id": key, "tool": tool, "params": params, "reason": reason},
            )
        )
        event.wait(self.timeout or None)
        self._events.pop(key, None)
        return self._decisions.pop(key, ApprovalDecision.DENY)

    def answer(self, key: str, decision: ApprovalDecision) -> None:
        """Give the answer of the user to the waiting tool."""
        self._decisions[key] = decision
        event = self._events.get(key)
        if event is not None:
            event.set()


class CoderApp(App):
    """The application: the conversation, the status bar and the input."""

    TITLE = "coder"
    CSS = """
    #conversation {
        height: 1fr;
        padding: 0 1;
    }
    #todos {
        dock: bottom;
    }
    """
    BINDINGS = [
        ("ctrl+c", "interrupt", "Interrupt"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: Config,
        cwd: Path,
        *,
        bus: EventBus | None = None,
        approver=None,
        session=None,
        store: SessionStore | None = None,
        loop=None,
    ) -> None:
        super().__init__()
        self.config = config
        self.cwd = Path(cwd)
        self.bus = bus or EventBus()
        self.approver = approver or TUIAprover(self.bus, config.ui.approval_timeout)
        self.store = store or SessionStore()
        self.loop = loop or build_loop(
            config, self.cwd, bus=self.bus, approver=self.approver, store=self.store, session=session
        )
        self.cards: dict[str, ToolCard] = {}
        self.current: MessageBlock | None = None
        """The message the agent is writing right now."""
        self.pending_approval: ApprovalPrompt | None = None
        self.approval_id = ""
        self.turn_running = threading.Event()
        self.interrupted = threading.Event()
        self.alive = True
        """False when the interface is gone; the events are dropped then."""

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status")
        yield VerticalScroll(id="conversation")
        yield TodoPanel(id="todos")
        yield Input(placeholder="输入消息…  (/help 查看命令)", id="input")

    def on_mount(self) -> None:
        self._subscribe()
        self._update_status()
        self.query_one("#input", Input).focus()

    # -- the events of the core -------------------------------------------

    def _subscribe(self) -> None:
        bus = self.loop.bus
        bus.subscribe(EventType.USER_MESSAGE, self._on_user_message)
        bus.subscribe(EventType.ASSISTANT_MESSAGE, self._on_assistant_message)
        bus.subscribe(EventType.TEXT_DELTA, self._on_text_delta)
        bus.subscribe(EventType.REASONING, self._on_reasoning)
        bus.subscribe(EventType.TOOL_CALL, self._on_tool_call)
        bus.subscribe(EventType.TOOL_RESULT, self._on_tool_result)
        bus.subscribe(EventType.APPROVAL_REQUEST, self._on_approval_request)
        bus.subscribe(EventType.STATE_CHANGE, self._on_state_change)
        bus.subscribe(EventType.ERROR, self._on_error)

    def _on_user_message(self, event: Event) -> None:
        self._ui(self._add_message, "user", event.payload.get("content", ""))

    def _on_assistant_message(self, event: Event) -> None:
        message = event.payload.get("message") or {}
        reasoning = (message.get("extra") or {}).get("reasoning", "")
        self._ui(self._add_message, "assistant", message.get("content", ""), reasoning)

    def _on_text_delta(self, event: Event) -> None:
        self._ui(self._append_text, event.payload.get("content", ""))

    def _on_reasoning(self, event: Event) -> None:
        self._ui(self._add_reasoning, event.payload.get("content", ""))

    def _on_tool_call(self, event: Event) -> None:
        for action in event.payload.get("actions", []):
            self._ui(self._add_card, action)

    def _on_tool_result(self, event: Event) -> None:
        payload = event.payload
        if "todos" in payload:
            self._ui(self.query_one("#todos", TodoPanel).show_todos, payload.get("todos") or [])
            return
        self._ui(self._finish_card, payload)

    def _on_approval_request(self, event: Event) -> None:
        self._ui(self._show_approval, event.payload)

    def _on_state_change(self, event: Event) -> None:
        self._ui(self._update_status, event.payload.get("state", ""))

    def _on_error(self, event: Event) -> None:
        self._ui(self._add_message, "error", event.payload.get("error", ""))

    # -- what the interface does with them -------------------------------

    def _add_message(self, role: str, content: str, reasoning: str = "") -> None:
        if role == "assistant" and self.current is not None:
            self.current.set_content(content)
            if reasoning:
                self.current.add_reasoning(reasoning)
            return
        block = MessageBlock(role, content, reasoning)
        self.query_one("#conversation", VerticalScroll).mount(block)
        self.current = block if role == "assistant" else None
        block.scroll_visible()

    def _append_text(self, text: str) -> None:
        if self.current is None:
            self._add_message("assistant", "")
        self.current.append(text)

    def _add_reasoning(self, text: str) -> None:
        if self.current is None:
            self._add_message("assistant", "")
        self.current.add_reasoning(text)

    def _add_card(self, action: dict) -> None:
        card = ToolCard(action.get("tool", ""), action.get("args", {}), action.get("tool_call_id", ""))
        self.cards[card.call_id] = card
        self.query_one("#conversation", VerticalScroll).mount(card)
        card.start()

    def _finish_card(self, payload: dict) -> None:
        card = self.cards.get(payload.get("tool_call_id", ""))
        if card is None:
            return
        card.finish(payload.get("content", ""), payload.get("is_error", False), payload.get("diff", ""))

    def _show_approval(self, payload: dict) -> None:
        tool = payload.get("tool", "")
        params = payload.get("params", {})
        diff = prospective_diff(tool, params, self.cwd) if tool in WRITE_TOOLS else ""
        prompt = ApprovalPrompt(tool, params, payload.get("reason", ""), diff)
        self.pending_approval = prompt
        self.approval_id = payload.get("id", "")
        self.query_one("#conversation", VerticalScroll).mount(prompt)
        self.query_one("#input", Input).disabled = True

    def _update_status(self, state: str = "") -> None:
        bar = self.query_one("#status", StatusBar)
        context = self.loop.context
        bar.update_status(
            model=self.config.model.model_name,
            tokens=context.estimated_tokens(self.loop.tools),
            window=context.config.context_window,
            cost=self.loop.model.total_cost,
            cwd=str(self.cwd),
            mode=self.loop.executor.policy.mode.value,
            state=state,
        )

    def _ui(self, callback, *args) -> None:
        """Run something in the thread of the interface."""
        if not self.alive:
            return
        if self._thread_id == threading.get_ident():
            callback(*args)
            return
        try:
            self.call_from_thread(callback, *args)
        except Exception:
            logger.debug("The interface is gone, the event is dropped", exc_info=True)

    def on_unmount(self) -> None:
        """The interface is gone; the events that still come are dropped."""
        self.alive = False

    # -- the input --------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._run_command(text)
            return
        self.run_worker(lambda: self._run_turn(text), thread=True, exclusive=True)

    def _run_turn(self, text: str) -> None:
        """The turn itself, in a thread."""
        self.interrupted.clear()
        self.turn_running.set()
        self.loop.cancel = self.interrupted.is_set
        try:
            result = self.loop.run_turn(text)
        except Exception as e:
            self._ui(self._add_message, "error", f"{type(e).__name__}: {e}")
            return
        finally:
            self.turn_running.clear()
        if result.stop_reason == "interrupted":
            self._ui(self._add_message, "error", "interrupted")
        elif result.error:
            self._ui(self._add_message, "error", result.error)

    def _run_command(self, line: str) -> None:
        """A slash command: quick enough to run in the interface itself."""
        context = CommandContext(
            loop=self.loop,
            session=self.loop.session,
            store=self.store,
            bus=self.loop.bus,
            cwd=self.cwd,
            config=self.config,
            policy=self.loop.executor.policy,
            checkpoints=self.loop.checkpoints,
            mcp=self.loop.mcp,
            output=lambda text: self._add_message("assistant", text),
        )
        run_command(context, line)

    # -- the keys ---------------------------------------------------------

    def on_key(self, event) -> None:
        if self.pending_approval is None or event.key not in ("y", "n", "a"):
            return
        decision = {"y": ApprovalDecision.ALLOW, "n": ApprovalDecision.DENY, "a": ApprovalDecision.ALWAYS}[event.key]
        self.pending_approval.remove()
        self.pending_approval = None
        self.approver.answer(self.approval_id, decision)
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()
        event.stop()

    def action_interrupt(self) -> None:
        """Stop the turn that is running."""
        if self.turn_running.is_set():
            self.interrupted.set()
            self._add_message("error", "interrupting…")
        else:
            self.exit()


def main(config: Config, cwd: Path, **kwargs) -> None:
    """Run the interface."""
    CoderApp(config, cwd, **kwargs).run()


__all__ = ["CoderApp", "TUIAprover", "main"]
