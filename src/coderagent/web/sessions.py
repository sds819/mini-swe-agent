"""The sessions of the web interface.

Every session has a worker thread: the turns and the commands run there, so the
event loop of the server is never blocked. The events of the core are translated
into items, put into a ring buffer and pushed to whoever is listening.
"""

import asyncio
import queue
import threading
from collections import deque
from pathlib import Path
from typing import Any

from coderagent.config.loader import load_config
from coderagent.config.schema import Config
from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.loop import AgentLoop
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import Session, SessionStore
from coderagent.run import build_loop, settle
from coderagent.web.approver import WebApprover
from coderagent.web.events import normalize

BUFFER_SIZE = 1000
"""How many items a session keeps for the browsers that come late."""


class SessionBusy(RuntimeError):
    """The session is already running a turn."""


class SessionRuntime:
    """One session: its loop, its worker thread, its buffer and its subscribers."""

    def __init__(
        self,
        config: Config,
        cwd: Path,
        *,
        store: SessionStore | None = None,
        session: Session | None = None,
        model: ModelBackend | None = None,
        permission_mode: str | None = None,
        registry: "SessionRegistry | None" = None,
    ) -> None:
        self.config = config
        self.cwd = Path(cwd)
        self.store = store or SessionStore()
        self.bus = EventBus()
        self.session = session or self.store.create(self.cwd)
        self.registry = registry
        self.approver = WebApprover(self.bus, self.session.id, config.ui.approval_timeout)
        self._model = model
        self._permission_mode = permission_mode
        self._loop: AgentLoop | None = None
        self.buffer: deque[dict] = deque(maxlen=BUFFER_SIZE)
        self.cancel = threading.Event()
        """Set to stop the turn that is running."""
        self.busy = threading.Event()
        """Set while a turn or a command is running."""
        self._lock = threading.Lock()
        self._seq = 0
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._work, daemon=True, name=f"session-{self.session.id}")
        self._worker.start()
        self._subscribe()
        self._replay()

    def _replay(self) -> None:
        """The items of the log, so that a browser that comes late sees them."""
        for event in self.store.events(self.session.id):
            for item in normalize(event):
                self.emit(item)

    # -- the events of the core -------------------------------------------

    def _subscribe(self) -> None:
        """Listen to every kind of event; the bus has no wildcard subscription."""
        for event_type in EventType:
            self.bus.subscribe(event_type, self._on_event)

    def _on_event(self, event: Event) -> None:
        for item in normalize(event):
            self.emit(item)

    def emit(self, item: dict) -> dict:
        """Put an item into the buffer and push it to the subscribers."""
        with self._lock:
            self._seq += 1
            item = {"seq": self._seq, **item}
            self.buffer.append(item)
            subscribers = list(self._subscribers)
        for loop, subscriber in subscribers:
            try:
                loop.call_soon_threadsafe(subscriber.put_nowait, item)
            except RuntimeError:  # pragma: no cover - the loop is gone
                pass
        return item

    def items(self, since: int = 0) -> list[dict]:
        """The items of the buffer that the browser has not seen yet."""
        with self._lock:
            return [item for item in self.buffer if item["seq"] > since]

    def attach(self, loop: asyncio.AbstractEventLoop, subscriber: asyncio.Queue, since: int = 0) -> None:
        """Add a subscriber and give it what it missed."""
        with self._lock:
            for item in self.buffer:
                if item["seq"] > since:
                    subscriber.put_nowait(item)
            self._subscribers.append((loop, subscriber))

    def detach(self, subscriber: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [(loop, item) for loop, item in self._subscribers if item is not subscriber]

    # -- the work ---------------------------------------------------------

    def submit(self, text: str) -> None:
        """Queue a message for the worker. Raises `SessionBusy` when it is running."""
        with self._lock:
            if self.busy.is_set():
                raise SessionBusy(f"the session {self.session.id} is running")
            self.busy.set()
        self._queue.put(text)

    def _work(self) -> None:
        while True:
            text = self._queue.get()
            try:
                self._execute(text)
            except Exception as error:
                self.emit({"kind": "error", "error": f"{type(error).__name__}: {error}"})
            finally:
                self.busy.clear()
                self._queue.task_done()

    def _execute(self, text: str) -> None:
        if text.startswith("/"):
            self._run_command(text)
            return
        self._run_turn(text)

    def _run_turn(self, text: str) -> None:
        loop = self.loop()
        self.cancel.clear()
        loop.cancel = self.cancel.is_set
        try:
            result = loop.run_turn(text)
        except Exception as error:
            self.emit({"kind": "error", "error": f"{type(error).__name__}: {error}"})
            self.emit({"kind": "turn_end", "stop_reason": "error", "cost": 0.0, "error": str(error)})
            return
        if result.stop_reason not in ("error", "cost_exceeded"):
            """A turn that failed has nothing to remember, and no money to do it."""
            settle(loop, self.config, self.cwd)
        self.emit(
            {
                "kind": "turn_end",
                "stop_reason": result.stop_reason,
                "cost": result.cost,
                "session_cost": loop.session.total_cost,
                "error": result.error,
            }
        )

    def _run_command(self, line: str) -> None:
        """A slash command. It may change the session, so the registry is told."""
        from coderagent.ui.commands import CommandContext
        from coderagent.ui.commands import run as run_command

        loop = self.loop()
        context = CommandContext(
            loop=loop,
            session=loop.session,
            store=self.store,
            bus=self.bus,
            cwd=self.cwd,
            config=self.config,
            policy=loop.executor.policy,
            checkpoints=loop.checkpoints,
            mcp=loop.mcp,
            output=lambda text: self.emit({"kind": "command_output", "text": text}),
        )
        run_command(context, line)
        if loop.session.id != self.session.id:
            self.switch_to(loop.session)
        self.emit({"kind": "command_end"})

    def switch_to(self, session: Session) -> None:
        """The session changed: the registry gets a new key for this runtime."""
        previous = self.session.id
        self.session = session
        self.approver.session_id = session.id
        if self.registry is not None:
            self.registry.rekey(self, previous, session.id)
        self.emit({"kind": "session_switched", "session_id": session.id, "previous_session_id": previous})

    def interrupt(self) -> None:
        """Ask the turn that is running to stop."""
        self.cancel.set()
        self.emit({"kind": "interrupted"})

    def resume(self) -> Session:
        """Continue the session of the log."""
        session = self.store.rebuild(self.session.id)
        if self._loop is not None:
            self._loop.switch_to(session)
        self.switch_to(session)
        return session

    # -- the state of the session -----------------------------------------

    def loop(self) -> AgentLoop:
        """The loop of this session. It is built when the first turn runs."""
        if self._loop is None:
            self._loop = build_loop(
                self.config,
                self.cwd,
                model=self._model,
                store=self.store,
                session=self.session,
                permission_mode=self._permission_mode,
                bus=self.bus,
                approver=self.approver,
            )
            self._loop.cancel = self.cancel.is_set
        return self._loop

    def status(self) -> dict[str, Any]:
        """The fields of the status bar."""
        loop = self._loop
        session = loop.session if loop else self.session
        return {
            "session_id": session.id,
            "model": getattr(loop.model.backend, "model_name", "") if loop else self.config.model.model_name,
            "tokens": loop.context.estimated_tokens(loop.tools) if loop else 0,
            "window": loop.context.config.context_window if loop else self.config.context.context_window,
            "cost": session.total_cost,
            "cwd": str(self.cwd),
            "mode": loop.executor.policy.mode.value if loop else self.config.permissions.mode,
            "state": session.state.value,
            "sandbox": self.config.sandbox.type,
            "busy": self.busy.is_set(),
        }


class SessionRegistry:
    """The sessions the web interface knows about."""

    def __init__(
        self,
        config: Config,
        cwd: Path,
        *,
        store: SessionStore | None = None,
        model: ModelBackend | None = None,
        permission_mode: str | None = None,
        config_spec: list[str] | None = None,
    ) -> None:
        self.config = config
        self.cwd = Path(cwd)
        self.store = store or SessionStore()
        self._model = model
        self._permission_mode = permission_mode
        self.config_spec = list(config_spec or [])
        """The command line overrides. The files are read again for every session."""
        self._runtimes: dict[str, SessionRuntime] = {}

    def create(self, session: Session | None = None) -> SessionRuntime:
        config = load_config(self.config_spec, cwd=self.cwd)
        """The configuration as it is now: what the user just wrote is in it."""
        runtime = SessionRuntime(
            config,
            self.cwd,
            store=self.store,
            session=session,
            model=self._model,
            permission_mode=self._permission_mode,
            registry=self,
        )
        self._runtimes[runtime.session.id] = runtime
        return runtime

    def get(self, session_id: str) -> SessionRuntime | None:
        return self._runtimes.get(session_id)

    def runtimes(self) -> list[SessionRuntime]:
        return list(self._runtimes.values())

    def rekey(self, runtime: SessionRuntime, old_id: str, new_id: str) -> None:
        """The session of a runtime changed; the registry follows."""
        self._runtimes.pop(old_id, None)
        self._runtimes[new_id] = runtime

    def list(self) -> list[Session]:
        return self.store.list(self.cwd)
