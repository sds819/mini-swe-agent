"""A turn that is stopped from the browser."""

import time

import pytest

pytest.importorskip("fastapi")

from coderagent.testing.scripted_model import ScriptedModel  # noqa: E402
from tests.coderagent.web.conftest import assistant, bash_call  # noqa: E402


def test_a_running_turn_can_be_interrupted(make_client, send, wait_for):
    def keep_going(messages):
        time.sleep(0.2)
        return assistant(tool_calls=[bash_call("echo tick", f"call_{len(messages)}")])

    client = make_client(model=ScriptedModel(side_effect=keep_going), permission_mode="bypass")
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "keep going")
    wait_for(client, session_id, "tool_call")

    response = client.post(f"/api/sessions/{session_id}/interrupt")

    assert response.status_code == 200
    items = wait_for(client, session_id, "turn_end")
    assert items[-1]["kind"] == "turn_end"
    assert items[-1]["stop_reason"] == "interrupted"
    assert [item["kind"] for item in items if item["kind"] == "interrupted"]


def test_a_session_that_was_interrupted_can_take_a_new_message(make_client, send, wait_for):
    def keep_going(messages):
        time.sleep(0.2)
        return assistant(tool_calls=[bash_call("echo tick", f"call_{len(messages)}")])

    client = make_client(model=ScriptedModel(side_effect=keep_going), permission_mode="bypass")
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "keep going")
    wait_for(client, session_id, "tool_call")
    client.post(f"/api/sessions/{session_id}/interrupt")
    wait_for(client, session_id, "turn_end")

    response = client.post(f"/api/sessions/{session_id}/messages", json={"text": "again"})

    assert response.status_code == 202
