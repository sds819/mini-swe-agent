"""The trace of a session: what happened, what it cost and where the money went.

The event log is the source of truth, so the trace is built from it. The format
of the trace is `coder-agent-1.0`, next to the `mini-swe-agent-1.1` of
mini-swe-agent.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from coderagent.core.events import Event, EventType

TRACE_FORMAT = "coder-agent-1.0"
SCOPE = "coderagent"


@dataclass
class Metrics:
    """What a session cost and how it went."""

    total_cost: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    per_tool: dict[str, int] = field(default_factory=dict)
    per_purpose_cost: dict[str, float] = field(default_factory=dict)
    per_model_cost: dict[str, float] = field(default_factory=dict)
    duration_seconds: float = 0.0
    compactions: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def report(self) -> str:
        """The cost of the session, as a report the user can read."""
        return "\n".join([*self.summary(), *self.attribution()])

    def summary(self) -> list[str]:
        return [
            f"cost: ${self.total_cost:.4f}",
            f"tokens: {self.total_tokens_in} in, {self.total_tokens_out} out",
            f"model calls: {self.model_calls}",
            f"tool calls: {self.tool_calls}",
            f"duration: {self.duration_seconds:.1f}s",
        ]

    def attribution(self) -> list[str]:
        """Where the money went."""
        lines = []
        if self.per_purpose_cost:
            lines.append("by purpose:")
            lines += [f"  {purpose:<12} ${cost:.4f}" for purpose, cost in sorted(self.per_purpose_cost.items())]
        if self.per_model_cost:
            lines.append("by model:")
            lines += [f"  {model:<24} ${cost:.4f}" for model, cost in sorted(self.per_model_cost.items())]
        if self.per_tool:
            lines.append("by tool:")
            lines += [f"  {tool:<12} {count}" for tool, count in sorted(self.per_tool.items())]
        return lines


def collect(events: list[Event]) -> Metrics:
    """The metrics of a session, from its events."""
    metrics = Metrics()
    tools: dict[str, str] = {}
    for event in events:
        payload = event.payload
        if event.type == EventType.ASSISTANT_MESSAGE:
            _model_call(metrics, payload)
        elif event.type == EventType.TOOL_CALL:
            for action in payload.get("actions") or []:
                metrics.tool_calls += 1
                tool = action.get("tool", "")
                metrics.per_tool[tool] = metrics.per_tool.get(tool, 0) + 1
                tools[action.get("tool_call_id", "")] = tool
        elif event.type == EventType.TOOL_RESULT:
            for message in payload.get("messages") or []:
                _sub_agent_cost(metrics, tools.get(message.get("tool_call_id", "")), message.get("content", ""))
        elif event.type == EventType.COMPACTION:
            metrics.compactions += 1
            cost = float(payload.get("cost") or 0.0)
            metrics.total_cost += cost
            metrics.per_purpose_cost["summarize"] = metrics.per_purpose_cost.get("summarize", 0.0) + cost
        elif event.type == EventType.REFLECTION:
            cost = float(payload.get("cost") or 0.0)
            metrics.total_cost += cost
            metrics.per_purpose_cost["reflect"] = metrics.per_purpose_cost.get("reflect", 0.0) + cost
            metrics.total_tokens_in += int(payload.get("tokens_in") or 0)
            metrics.total_tokens_out += int(payload.get("tokens_out") or 0)
            model = str(payload.get("model") or "")
            if model:
                metrics.per_model_cost[model] = metrics.per_model_cost.get(model, 0.0) + cost
        elif event.type == EventType.ERROR:
            metrics.errors += 1
    timestamps = [event.timestamp for event in events if event.timestamp]
    if len(timestamps) > 1:
        metrics.duration_seconds = max(timestamps) - min(timestamps)
    return metrics


def trace(events: list[Event], session=None) -> dict[str, Any]:
    """The whole session, as a trace."""
    return {
        "trajectory_format": TRACE_FORMAT,
        "session": _session(session),
        "events": [event.to_dict() for event in events],
        "metrics": collect(events).to_dict(),
    }


def otel(events: list[Event], session=None) -> dict[str, Any]:
    """The session as OTLP/JSON: one span per turn, one per tool call."""
    session_id = getattr(session, "id", "") or (events[0].session_id if events else "")
    trace_id = _hex(session_id, 32)
    spans = []
    turn: dict[str, Any] | None = None
    children: list[dict[str, Any]] = []
    for event in events:
        if event.type == EventType.USER_MESSAGE:
            if turn is not None:
                turn["spans"] = children
                spans.append(turn)
            turn = {
                "traceId": trace_id,
                "spanId": _hex(f"{session_id}:{event.timestamp}", 16),
                "name": "turn",
                "kind": 1,
                "startTimeUnixNano": _nanos(event.timestamp),
                "endTimeUnixNano": _nanos(event.timestamp),
                "attributes": [{"key": "session.id", "value": {"stringValue": session_id}}],
                "spans": [],
            }
            children = []
        elif turn is not None and event.type == EventType.TOOL_CALL:
            for index, action in enumerate(payload_actions(event)):
                children.append(
                    {
                        "traceId": trace_id,
                        "spanId": _hex(f"{session_id}:{event.timestamp}:{index}", 16),
                        "parentSpanId": turn["spanId"],
                        "name": f"tool.{action.get('tool', '')}",
                        "kind": 1,
                        "startTimeUnixNano": _nanos(event.timestamp),
                        "endTimeUnixNano": _nanos(event.timestamp),
                        "attributes": [
                            {"key": "tool.name", "value": {"stringValue": action.get("tool", "")}},
                            {"key": "tool.call_id", "value": {"stringValue": action.get("tool_call_id", "")}},
                        ],
                    }
                )
        elif turn is not None:
            turn["endTimeUnixNano"] = _nanos(event.timestamp)
    if turn is not None:
        turn["spans"] = children
        spans.append(turn)
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "session.id", "value": {"stringValue": session_id}},
                        {"key": "session.cwd", "value": {"stringValue": str(getattr(session, "cwd", ""))}},
                    ]
                },
                "scopeSpans": [{"scope": {"name": SCOPE}, "spans": spans}],
            }
        ]
    }


def payload_actions(event: Event) -> list[dict]:
    return event.payload.get("actions") or []


def _model_call(metrics: Metrics, payload: dict) -> None:
    message = payload.get("message") or {}
    extra = message.get("extra") or {}
    cost = float(extra.get("cost") or payload.get("cost") or 0.0)
    metrics.model_calls += 1
    metrics.total_cost += cost
    metrics.total_tokens_in += int(extra.get("tokens_in") or 0)
    metrics.total_tokens_out += int(extra.get("tokens_out") or 0)
    purpose = str(extra.get("purpose") or "main")
    metrics.per_purpose_cost[purpose] = metrics.per_purpose_cost.get(purpose, 0.0) + cost
    model = str(extra.get("model") or "")
    if model:
        metrics.per_model_cost[model] = metrics.per_model_cost.get(model, 0.0) + cost


def _sub_agent_cost(metrics: Metrics, tool: str, content: str) -> None:
    """The cost of a sub agent is the cost of the purpose it ran for."""
    if tool != "task":
        return
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(result, dict):
        return
    cost = float(result.get("cost") or 0.0)
    purpose = str(result.get("purpose") or "subagent")
    metrics.total_cost += cost
    metrics.total_tokens_in += int(result.get("tokens_in") or 0)
    metrics.total_tokens_out += int(result.get("tokens_out") or 0)
    metrics.per_purpose_cost[purpose] = metrics.per_purpose_cost.get(purpose, 0.0) + cost


def _session(session) -> dict[str, Any]:
    if session is None:
        return {}
    return {
        "id": session.id,
        "cwd": str(session.cwd),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "state": session.state.value,
        "model_name": session.model_name,
        "permission_mode": session.permission_mode,
        "turn_count": session.turn_count,
        "total_cost": session.total_cost,
    }


def _hex(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def _nanos(timestamp: float) -> str:
    return str(int(timestamp * 1_000_000_000))


__all__ = ["Metrics", "SCOPE", "TRACE_FORMAT", "collect", "otel", "trace"]
