"""The sessions of the web interface: create, list, replay, fork and resume."""

import pytest

pytest.importorskip("fastapi")

from coderagent.core.telemetry import collect  # noqa: E402


def test_a_new_session_is_created_and_listed(make_client):
    client = make_client()
    created = client.post("/api/sessions")

    assert created.status_code == 201
    session_id = created.json()["id"]
    assert [session["id"] for session in client.get("/api/sessions").json()["sessions"]] == [session_id]
    assert client.get(f"/api/sessions/{session_id}").json()["id"] == session_id
    assert client.get(f"/api/sessions/{session_id}").json()["state"] == "idle"


def test_a_session_that_does_not_exist_is_not_found(make_client):
    client = make_client()

    assert client.get("/api/sessions/nope").status_code == 404


def test_the_status_of_a_session_shows_where_it_is(make_client, tmp_path):
    client = make_client()
    session_id = client.post("/api/sessions").json()["id"]

    status = client.get(f"/api/sessions/{session_id}/status").json()

    assert status["session_id"] == session_id
    assert status["cwd"] == str(tmp_path)
    assert status["busy"] is False
    assert status["mode"] == "default"


def test_the_events_of_a_session_are_replayed(make_client, send, wait_for):
    client = make_client(responses=[{"role": "assistant", "content": "hi", "extra": {"cost": 0.1}}])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    items = client.get(f"/api/sessions/{session_id}/events").json()["items"]
    kinds = [item["kind"] for item in items]

    assert "user_message" in kinds
    assert "assistant_message" in kinds
    assert kinds.count("tool_result") == 0
    assert [item["content"] for item in items if item["kind"] == "user_message"] == ["hello"]


def test_the_metrics_of_a_session_are_the_cost_of_the_log(make_client, send, wait_for):
    client = make_client(responses=[{"role": "assistant", "content": "hi", "extra": {"cost": 0.25}}])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    metrics = client.get(f"/api/sessions/{session_id}/metrics").json()

    assert metrics["total_cost"] == pytest.approx(0.25)
    assert metrics["model_calls"] == 1
    assert metrics["total_cost"] == collect(client.app.state.registry.store.events(session_id)).total_cost


def test_a_fork_copies_the_session_and_leaves_the_original(make_client, send, wait_for):
    client = make_client(responses=[{"role": "assistant", "content": "hi", "extra": {"cost": 0.1}}])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")
    before = client.get(f"/api/sessions/{session_id}/events").json()["items"]

    forked = client.post(f"/api/sessions/{session_id}/fork").json()

    assert forked["forked_from"] == session_id
    assert forked["id"] != session_id
    assert client.get(f"/api/sessions/{forked['id']}/events").json()["items"][: len(before)] == before
    assert client.get(f"/api/sessions/{session_id}/events").json()["items"] == before


def test_a_resumed_session_keeps_its_history(make_client, send, wait_for):
    client = make_client(responses=[{"role": "assistant", "content": "hi", "extra": {"cost": 0.1}}])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "hello")
    wait_for(client, session_id, "turn_end")

    resumed = client.post(f"/api/sessions/{session_id}/resume").json()

    assert resumed["id"] == session_id
    assert client.get(f"/api/sessions/{session_id}").json()["turns"] == 1


def test_a_session_that_is_running_refuses_a_second_message(make_client):
    client = make_client(responses=[{"role": "assistant", "content": "hi", "extra": {"cost": 0.1}}])
    session_id = client.post("/api/sessions").json()["id"]

    first = client.post(f"/api/sessions/{session_id}/messages", json={"text": "hello"})
    second = client.post(f"/api/sessions/{session_id}/messages", json={"text": "hello again"})

    assert first.status_code == 202
    assert second.status_code == 409
