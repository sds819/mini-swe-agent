"""Translate the events of the core into the items the browser renders.

The core speaks in events, the browser in items. Most events are one item; a tool
call is one item per action, and a tool result is one item per observation.
"""

from coderagent.core.events import Event, EventType
from coderagent.ui.widgets.tool_card import summarize


def normalize(event: Event) -> list[dict]:
    """The items of one event. An event that says nothing renders nothing."""
    payload = event.payload
    if event.type == EventType.USER_MESSAGE:
        return [{"kind": "user_message", "content": payload.get("content", "")}]
    if event.type == EventType.ASSISTANT_MESSAGE:
        message = payload.get("message") or {}
        return [
            {
                "kind": "assistant_message",
                "content": message.get("content", ""),
                "reasoning": (message.get("extra") or {}).get("reasoning", ""),
            }
        ]
    if event.type == EventType.TEXT_DELTA:
        return [{"kind": "text_delta", "content": payload.get("content", "")}]
    if event.type == EventType.REASONING:
        return [{"kind": "reasoning_delta", "content": payload.get("content", "")}]
    if event.type == EventType.TOOL_CALL:
        return [_tool_call(action) for action in payload.get("actions") or []]
    if event.type == EventType.TOOL_RESULT:
        return _tool_result(payload)
    if event.type == EventType.APPROVAL_REQUEST:
        return [
            {
                "kind": "approval_request",
                "id": payload.get("id", ""),
                "tool": payload.get("tool", ""),
                "params": payload.get("params", {}),
                "reason": payload.get("reason", ""),
            }
        ]
    if event.type == EventType.APPROVAL_RESPONSE:
        return [
            {
                "kind": "approval_response",
                "id": payload.get("id", ""),
                "decision": payload.get("decision", ""),
                "timed_out": bool(payload.get("timed_out")),
            }
        ]
    if event.type == EventType.STATE_CHANGE:
        return [{"kind": "state", **{key: value for key, value in payload.items() if value is not None}}]
    if event.type == EventType.COMPACTION:
        return [{"kind": "compaction", "tokens": payload.get("tokens", 0), "cost": payload.get("cost", 0.0)}]
    if event.type == EventType.REFLECTION:
        return [
            {
                "kind": "reflection",
                "cost": payload.get("cost", 0.0),
                "purpose": payload.get("purpose", ""),
                "model": payload.get("model", ""),
                "project_facts": payload.get("project_facts", []),
                "user_preferences": payload.get("user_preferences", []),
            }
        ]
    if event.type == EventType.REVERTED:
        return [{"kind": "reverted", "messages": payload.get("messages", 0)}]
    if event.type == EventType.ERROR:
        return [{"kind": "error", "error": payload.get("error", "")}]
    return []


def _tool_call(action: dict) -> dict:
    args = action.get("args") or {}
    return {
        "kind": "tool_call",
        "tool": action.get("tool", ""),
        "args": args,
        "summary": summarize(args),
        "tool_call_id": action.get("tool_call_id", ""),
    }


def _tool_result(payload: dict) -> list[dict]:
    """A tool result comes in two shapes: from the executor and from the context."""
    items = []
    if "tool" in payload:
        """The executor knows the tool and the diff of the change."""
        items.append(
            {
                "kind": "tool_result",
                "tool": payload.get("tool", ""),
                "tool_call_id": payload.get("tool_call_id", ""),
                "content": payload.get("content", ""),
                "is_error": bool(payload.get("is_error")),
                "diff": payload.get("diff", ""),
            }
        )
    for message in payload.get("messages") or []:
        """The context records what the model gets to see."""
        items.append(
            {
                "kind": "tool_result",
                "tool_call_id": message.get("tool_call_id", ""),
                "content": message.get("content", ""),
                "is_error": str(message.get("content", "")).startswith("Error:"),
                "diff": "",
            }
        )
    if payload.get("todos"):
        items.append({"kind": "todos", "todos": payload.get("todos") or []})
    return items
