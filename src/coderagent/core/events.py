"""Event system: the single source of truth for everything that happens in a session."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("coderagent.events")


class EventType(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    STATE_CHANGE = "state_change"
    COMPACTION = "compaction"
    REVERTED = "reverted_to"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    session_id: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event | None":
        """Build an event from its serialized form. Unknown types are skipped (return None)."""
        try:
            event_type = EventType(data["type"])
        except (KeyError, ValueError):
            logger.debug("Skipping event with unknown type: %s", data.get("type"))
            return None
        return cls(
            type=event_type,
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp", 0.0),
            payload=data.get("payload") or {},
        )


class EventBus:
    """Synchronous publish/subscribe. UI subscribes, the core publishes."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event: Event) -> None:
        for callback in list(self._subscribers.get(event.type, [])):
            try:
                callback(event)
            except Exception:
                logger.exception("Event subscriber failed for %s", event.type)
