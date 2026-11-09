"""A turn that runs in the browser: the items, the tool output and the cost."""

import sys

import pytest

pytest.importorskip("fastapi")

from tests.coderagent.web.conftest import assistant, bash_call  # noqa: E402


def test_a_turn_shows_the_conversation_and_the_tool(make_client, send, wait_for):
    client = make_client(
        responses=[
            assistant(tool_calls=[bash_call("echo hello")]),
            assistant("all done", cost=0.5),
        ],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")
    kinds = [item["kind"] for item in items]

    assert kinds.index("user_message") < kinds.index("tool_call")
    assert kinds[-1] == "turn_end"
    assert [item["content"] for item in items if item["kind"] == "user_message"] == ["say hello"]
    assert [item["content"] for item in items if item["kind"] == "assistant_message"] == ["", "all done"]


def test_the_tool_card_knows_which_tool_was_called(make_client, send, wait_for):
    client = make_client(
        responses=[assistant(tool_calls=[bash_call("echo hello")]), assistant("done")],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")
    call = [item for item in items if item["kind"] == "tool_call"][0]

    assert call["tool"] == "bash"
    assert call["args"] == {"command": "echo hello"}
    assert call["tool_call_id"] == "call_1"
    assert "echo hello" in call["summary"]


def test_the_output_of_the_tool_is_in_the_items(make_client, send, wait_for):
    client = make_client(
        responses=[assistant(tool_calls=[bash_call("echo hello")]), assistant("done")],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")
    results = [item for item in items if item["kind"] == "tool_result"]

    assert "hello" in results[0]["content"]
    assert results[0]["is_error"] is False
    assert results[0]["tool_call_id"] == "call_1"


def test_the_turn_reports_what_it_cost(make_client, send, wait_for):
    client = make_client(
        responses=[assistant(tool_calls=[bash_call("echo hello")]), assistant("done", cost=0.5)],
        permission_mode="bypass",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")
    end = items[-1]

    assert end["kind"] == "turn_end"
    assert end["stop_reason"] == "end_turn"
    assert end["cost"] == pytest.approx(0.5)
    assert end["session_cost"] == pytest.approx(0.5)


def test_a_rewritten_prompt_keeps_what_the_user_typed(make_client, send, wait_for, tmp_path):
    """The browser shows the prompt of the model, and what the user wrote."""
    script = tmp_path / "rewrite.py"
    script.write_text(
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "print(json.dumps({'updatedInput': data['prompt'] + ' (rewritten)'}))\n",
        encoding="utf-8",
    )
    client = make_client(
        responses=[assistant("all done")],
        project_config=(
            "hooks:\n"
            "  events:\n"
            "    UserPromptSubmit:\n"
            "      - hooks:\n"
            "          - type: command\n"
            f'            command: "{sys.executable} {script}"\n'
        ),
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")
    message = [item for item in items if item["kind"] == "user_message"][0]

    assert message["content"] == "say hello (rewritten)"
    assert message["original"] == "say hello"


def test_an_empty_message_is_refused(make_client):
    client = make_client()
    session_id = client.post("/api/sessions").json()["id"]

    assert client.post(f"/api/sessions/{session_id}/messages", json={"text": "   "}).status_code == 400


def test_a_model_that_fails_ends_the_turn_with_an_error(make_client, send, wait_for):
    client = make_client(responses=[])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")

    items = wait_for(client, session_id, "turn_end")

    assert items[-1]["stop_reason"] == "error"
    assert items[-1]["error"]
    assert [item["kind"] for item in items if item["kind"] == "error"]
