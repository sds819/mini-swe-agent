"""The sub agents in the web interface: the same ones the `/agents` command shows."""

import pytest

pytest.importorskip("fastapi")


def test_the_sub_agents_are_listed(make_client):
    client = make_client()

    data = client.get("/api/agents").json()

    names = [agent["name"] for agent in data["agents"]]
    assert {"code-explorer", "verifier", "refactorer"} <= set(names)


def test_the_turns_that_count_are_shown(make_client):
    """The turns of the sub agent, held down by the ceiling of the configuration."""
    client = make_client()

    data = client.get("/api/agents").json()
    turns = {agent["name"]: agent["turns"] for agent in data["agents"]}

    assert turns["code-explorer"] == 15
    assert turns["refactorer"] == 30
    assert data["ceiling"] == 0


def test_the_ceiling_of_the_configuration_holds_the_turns_down(make_client):
    client = make_client(project_config="agent:\n  subagent_max_turns: 20\n")

    data = client.get("/api/agents").json()
    turns = {agent["name"]: agent["turns"] for agent in data["agents"]}

    assert turns["code-explorer"] == 15
    assert turns["refactorer"] == 20
    assert data["ceiling"] == 20


def test_the_tools_of_a_sub_agent_are_shown(make_client):
    client = make_client()

    data = client.get("/api/agents").json()
    explorer = next(agent for agent in data["agents"] if agent["name"] == "code-explorer")

    assert explorer["tools"] == ["read", "grep", "glob", "ls"]
    assert explorer["purpose"] == "cheap"
    assert explorer["description"]


def test_the_chat_page_has_a_place_for_the_sub_agents(make_client):
    client = make_client()

    page = client.get("/").text

    assert 'id="agents"' in page
    assert "Sub agents" in page


def test_the_page_in_chinese_has_one_too(make_client):
    client = make_client()

    page = client.get("/?lang=zh").text

    assert 'id="agents"' in page
    assert "子 agent" in page
