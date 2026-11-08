"""The event stream: the frames the browser receives."""

import json

import pytest

pytest.importorskip("fastapi")

from coderagent.web.events import TRANSIENT_KINDS  # noqa: E402
from tests.coderagent.web.conftest import assistant, bash_call  # noqa: E402


def frames(response) -> list[dict]:
    """The items of an event stream."""
    return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def test_the_stream_ends_with_the_turn(make_client, send, wait_for):
    client = make_client(responses=[assistant("hi", cost=0.1)], permission_mode="bypass")
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    with client.stream("GET", f"/api/sessions/{session_id}/stream?since=0") as response:
        items = frames(response)

    assert items[-1]["kind"] == "turn_end"
    assert all("seq" in item and "kind" in item for item in items)
    assert [item["seq"] for item in items] == sorted(item["seq"] for item in items)


def test_the_stream_says_the_same_as_the_buffer(make_client, send, wait_for):
    client = make_client(
        responses=[assistant(tool_calls=[bash_call("echo hello")]), assistant("done")],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    with client.stream("GET", f"/api/sessions/{session_id}/stream?since=0") as response:
        streamed = frames(response)
    buffered = client.get(f"/api/sessions/{session_id}/items").json()["items"]

    assert [item for item in streamed if item["kind"] not in TRANSIENT_KINDS] == buffered


def test_the_streaming_pieces_are_not_kept(make_client, send, wait_for):
    """A long answer must not push the history out of the buffer."""
    client = make_client(responses=[assistant("hi", cost=0.1)], permission_mode="bypass")
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    buffered = client.get(f"/api/sessions/{session_id}/items").json()["items"]
    kinds = [item["kind"] for item in buffered]

    assert "text_delta" not in kinds
    assert "assistant_message" in kinds
    assert [item["content"] for item in buffered if item["kind"] == "assistant_message"] == ["hi"]


def test_the_stream_skips_what_the_browser_has_seen(make_client, send, wait_for):
    client = make_client(
        responses=[assistant("hi", cost=0.1), assistant("again", cost=0.1)],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")
    last = client.get(f"/api/sessions/{session_id}/items").json()["items"][-1]["seq"]

    send(client, session_id, "and again")
    with client.stream("GET", f"/api/sessions/{session_id}/stream?since={last}") as response:
        rest = frames(response)

    assert [item["kind"] for item in rest][-1] == "turn_end"
    assert all(item["seq"] > last for item in rest)
    assert [item["content"] for item in rest if item["kind"] == "user_message"] == ["and again"]
