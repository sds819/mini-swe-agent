"""The approvals: the browser decides whether a tool may run."""

import pytest

pytest.importorskip("fastapi")

from tests.coderagent.web.conftest import assistant, bash_call  # noqa: E402


def test_an_allowed_tool_runs(make_client, send, wait_for):
    client = make_client(responses=[assistant(tool_calls=[bash_call("sh -c 'echo approved'")]), assistant("done")])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "run it")

    items = wait_for(client, session_id, "approval_request")
    request = [item for item in items if item["kind"] == "approval_request"][0]

    assert request["tool"] == "bash"
    assert request["params"] == {"command": "sh -c 'echo approved'"}
    assert client.post(f"/api/approvals/{request['id']}", json={"decision": "allow"}).status_code == 200

    items = wait_for(client, session_id, "turn_end")
    results = [item for item in items if item["kind"] == "tool_result"]
    assert "approved" in results[0]["content"]
    assert [item["decision"] for item in items if item["kind"] == "approval_response"] == ["allow"]


def test_a_denied_tool_does_not_run(make_client, send, wait_for):
    client = make_client(responses=[assistant(tool_calls=[bash_call("sh -c 'echo approved'")]), assistant("done")])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "run it")

    items = wait_for(client, session_id, "approval_request")
    request = [item for item in items if item["kind"] == "approval_request"][0]
    client.post(f"/api/approvals/{request['id']}", json={"decision": "deny"})

    items = wait_for(client, session_id, "turn_end")
    results = [item for item in items if item["kind"] == "tool_result"]
    assert "denied" in results[0]["content"]
    assert [item["decision"] for item in items if item["kind"] == "approval_response"] == ["deny"]


def test_an_approval_that_nobody_answers_is_denied(make_client, send, wait_for):
    client = make_client(
        responses=[assistant(tool_calls=[bash_call("sh -c 'echo approved'")]), assistant("done")],
        project_config="ui:\n  approval_timeout: 1\n",
    )
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "run it")

    items = wait_for(client, session_id, "approval_response", timeout=20)
    response = [item for item in items if item["kind"] == "approval_response"][0]

    assert response["timed_out"] is True
    assert response["decision"] == "deny"


def test_an_approval_that_nobody_waited_for_is_not_found(make_client):
    client = make_client()

    assert client.post("/api/approvals/42", json={"decision": "allow"}).status_code == 404


def test_a_decision_that_does_not_exist_is_refused(make_client):
    client = make_client()

    assert client.post("/api/approvals/1", json={"decision": "maybe"}).status_code == 400


def test_a_write_without_the_client_header_is_refused(make_client):
    client = make_client()

    assert (
        client.post("/api/approvals/1", json={"decision": "allow"}, headers={"X-Coder-Client": ""}).status_code == 403
    )
    session_id = client.post("/api/sessions").json()["id"]
    assert (
        client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "hello"}, headers={"X-Coder-Client": ""}
        ).status_code
        == 403
    )
