"""Approval over HTTP: the tool waits in its thread until the browser answers."""

import threading
import time

from coderagent.core.events import Event, EventBus, EventType
from coderagent.tools.permissions import ApprovalDecision

DEFAULT_TIMEOUT = 300
"""Seconds to wait for an answer before the tool is denied."""


class WebApprover:
    """Asks the browser whether a tool may run.

    The request goes into the event stream, the answer comes back over HTTP and
    wakes the tool up. Without an answer the tool is denied, never run.
    """

    def __init__(self, bus: EventBus, session_id: str = "", timeout: int = 0) -> None:
        self.bus = bus
        self.session_id = session_id
        self.timeout = timeout or DEFAULT_TIMEOUT
        self._events: dict[str, threading.Event] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision:
        """Wait until the user answers."""
        with self._lock:
            self._counter += 1
            key = str(self._counter)
            event = threading.Event()
            self._events[key] = event
        self.bus.publish(
            Event(
                type=EventType.APPROVAL_REQUEST,
                session_id=self.session_id,
                timestamp=time.time(),
                payload={"id": key, "tool": tool, "params": params, "reason": reason},
            )
        )
        if not event.wait(self.timeout):
            with self._lock:
                self._events.pop(key, None)
                self._decisions.pop(key, None)
            self._respond(key, "deny", timed_out=True)
            return ApprovalDecision.DENY
        with self._lock:
            self._events.pop(key, None)
            return self._decisions.pop(key, ApprovalDecision.DENY)

    def answer(self, key: str, decision: ApprovalDecision) -> bool:
        """Give the answer of the user to the waiting tool."""
        with self._lock:
            if key not in self._events:
                return False
            self._decisions[key] = decision
            self._events[key].set()
        self._respond(key, decision.value)
        return True

    def _respond(self, key: str, decision: str, timed_out: bool = False) -> None:
        """Tell the browser what the answer was."""
        self.bus.publish(
            Event(
                type=EventType.APPROVAL_RESPONSE,
                session_id=self.session_id,
                timestamp=time.time(),
                payload={"id": key, "decision": decision, "timed_out": timed_out},
            )
        )
