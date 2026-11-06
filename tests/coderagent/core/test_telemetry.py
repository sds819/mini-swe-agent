"""The trace of a session and the metrics that go with it."""

import json

import pytest

from coderagent.core.events import Event, EventType
from coderagent.core.telemetry import TRACE_FORMAT, collect, otel, trace


def _event(event_type: EventType, payload: dict, timestamp: float = 1.0) -> Event:
    return Event(type=event_type, session_id="s1", timestamp=timestamp, payload=payload)


def _assistant(
    cost: float = 0.1, model: str = "m1", purpose: str = "main", tokens: int = 100, timestamp: float = 1.0
) -> Event:
    return _event(
        EventType.ASSISTANT_MESSAGE,
        {
            "message": {
                "role": "assistant",
                "content": "hi",
                "extra": {
                    "cost": cost,
                    "model": model,
                    "purpose": purpose,
                    "tokens_in": tokens,
                    "tokens_out": tokens // 4,
                },
            },
            "cost": cost,
        },
        timestamp,
    )


def test_the_cost_of_the_calls_is_added_up():
    metrics = collect([_assistant(0.1), _assistant(0.2)])
    assert metrics.total_cost == pytest.approx(0.3)
    assert metrics.model_calls == 2


def test_the_tokens_are_added_up():
    metrics = collect([_assistant(tokens=100), _assistant(tokens=200)])
    assert metrics.total_tokens_in == 300
    assert metrics.total_tokens_out == 75


def test_the_cost_is_attributed_to_the_purpose():
    metrics = collect([_assistant(0.1, purpose="main"), _assistant(0.2, purpose="cheap")])
    assert metrics.per_purpose_cost == {"main": 0.1, "cheap": 0.2}


def test_the_cost_is_attributed_to_the_model():
    metrics = collect([_assistant(0.1, model="a"), _assistant(0.2, model="b")])
    assert metrics.per_model_cost == {"a": 0.1, "b": 0.2}


def test_the_tools_are_counted():
    events = [
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "read", "tool_call_id": "1"}]}),
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "read", "tool_call_id": "2"}]}),
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "bash", "tool_call_id": "3"}]}),
    ]
    metrics = collect(events)
    assert metrics.per_tool == {"read": 2, "bash": 1}
    assert metrics.tool_calls == 3


def test_the_cost_of_a_sub_agent_is_attributed_to_its_purpose():
    events = [
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "task", "tool_call_id": "1"}]}),
        _event(
            EventType.TOOL_RESULT,
            {
                "messages": [
                    {"role": "tool", "tool_call_id": "1", "content": json.dumps({"cost": 0.5, "purpose": "cheap"})}
                ]
            },
        ),
    ]
    metrics = collect(events)
    assert metrics.per_purpose_cost == {"cheap": 0.5}


def test_a_tool_result_that_is_not_json_is_ignored():
    events = [
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "task", "tool_call_id": "1"}]}),
        _event(EventType.TOOL_RESULT, {"messages": [{"role": "tool", "tool_call_id": "1", "content": "not json"}]}),
    ]
    assert collect(events).per_purpose_cost == {}


def test_the_compactions_and_the_errors_are_counted():
    metrics = collect([_event(EventType.COMPACTION, {}), _event(EventType.ERROR, {"error": "x"})])
    assert metrics.compactions == 1
    assert metrics.errors == 1


def test_the_duration_is_the_time_between_the_events():
    metrics = collect([_event(EventType.USER_MESSAGE, {"content": "hi"}, 1.0), _assistant(timestamp=4.0)])
    assert metrics.duration_seconds == 3.0


def test_the_report_says_where_the_money_went():
    metrics = collect([_assistant(0.1, model="a")])
    report = metrics.report()
    assert "cost: $0.1000" in report
    assert "by purpose:" in report
    assert "by model:" in report


def test_the_trace_has_the_format_and_the_events():
    events = [_event(EventType.USER_MESSAGE, {"content": "hi"})]
    data = trace(events)
    assert data["trajectory_format"] == TRACE_FORMAT
    assert data["events"][0]["payload"]["content"] == "hi"
    assert data["metrics"]["model_calls"] == 0


def test_the_trace_names_the_session():
    class Session:
        id = "s1"
        cwd = "/tmp"
        created_at = 1.0
        updated_at = 2.0
        state = type("State", (), {"value": "done"})()
        model_name = "m1"
        permission_mode = "default"
        turn_count = 1
        total_cost = 0.5

    data = trace([], Session())
    assert data["session"]["id"] == "s1"
    assert data["session"]["state"] == "done"


def test_the_otel_export_has_one_span_per_turn():
    events = [
        _event(EventType.USER_MESSAGE, {"content": "hi"}, 1.0),
        _event(EventType.TOOL_CALL, {"actions": [{"tool": "read", "tool_call_id": "1"}]}, 2.0),
        _event(EventType.USER_MESSAGE, {"content": "again"}, 3.0),
    ]
    spans = otel(events)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2
    assert spans[0]["name"] == "turn"
    assert spans[0]["spans"][0]["name"] == "tool.read"
    assert spans[0]["spans"][0]["parentSpanId"] == spans[0]["spanId"]


def test_the_otel_export_has_the_session_as_a_resource():
    class Session:
        id = "s1"
        cwd = "/tmp"

    resource = otel([], Session())["resourceSpans"][0]["resource"]
    assert {"key": "session.id", "value": {"stringValue": "s1"}} in resource["attributes"]
