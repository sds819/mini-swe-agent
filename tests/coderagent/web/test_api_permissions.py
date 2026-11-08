"""The permission settings of the web interface: the files and the running session."""

import pytest
import yaml

pytest.importorskip("fastapi")

from coderagent.paths import config_home  # noqa: E402
from coderagent.web import config_api  # noqa: E402
from tests.coderagent.web.conftest import assistant  # noqa: E402


def test_the_permissions_are_written_to_the_user_file(tmp_path):
    user_file = config_home() / "config.yaml"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")

    config_api.write_user_permissions({"mode": "bypass", "deny_paths": ["secrets/"], "include_dirs": ["/tmp"]})

    data = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert data["permissions"]["mode"] == "bypass"
    assert data["permissions"]["deny_paths"] == ["secrets/"]
    assert data["permissions"]["include_dirs"] == ["/tmp"]
    assert data["agent"]["max_turns"] == 7
    """The sections the page does not know about stay as they are."""


def test_the_rules_of_the_permissions_are_kept(tmp_path):
    user_file = config_home() / "config.yaml"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text(
        "permissions:\n  rules:\n  - tool: bash\n    pattern: ls\n    decision: allow\n", encoding="utf-8"
    )

    config_api.write_user_permissions({"mode": "readonly"})

    data = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert data["permissions"]["rules"] == [{"tool": "bash", "pattern": "ls", "decision": "allow"}]
    """The rules are the business of the approvals, not of the settings page."""


def test_the_project_file_is_never_written(tmp_path):
    (tmp_path / ".coderagent").mkdir()
    (tmp_path / ".coderagent" / "config.yaml").write_text("permissions:\n  mode: plan\n", encoding="utf-8")

    config_api.write_user_permissions({"mode": "bypass"})

    assert "bypass" not in (tmp_path / ".coderagent" / "config.yaml").read_text(encoding="utf-8")


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        config_api.write_user_permissions({"mode": "turbo"})
    """A mode that does not exist must not reach the file."""


def test_the_view_shows_the_settings_of_the_files(tmp_path):
    (tmp_path / ".coderagent").mkdir()
    (tmp_path / ".coderagent" / "config.yaml").write_text("permissions:\n  mode: plan\n", encoding="utf-8")

    view = config_api.permissions_view(tmp_path)

    assert view["mode"] == "plan"
    assert view["modes"] == ["default", "acceptEdits", "plan", "bypass", "readonly"]
    assert view["source"]["mode"] == "project"
    assert view["server_mode"] == ""


def test_the_server_mode_wins_over_the_files(tmp_path):
    (tmp_path / ".coderagent").mkdir()
    (tmp_path / ".coderagent" / "config.yaml").write_text("permissions:\n  mode: plan\n", encoding="utf-8")

    view = config_api.permissions_view(tmp_path, server_mode="bypass")

    assert view["mode"] == "bypass"
    assert view["source"]["mode"] == "server"
    """The user has to see that the file does not decide the mode here."""


def test_the_api_writes_the_permissions_to_the_user_file(make_client):
    client = make_client()
    user_file = config_home() / "config.yaml"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")

    response = client.put("/api/config/permissions", json={"mode": "bypass", "deny_paths": ["secrets/"]})

    assert response.status_code == 200
    assert response.json()["permissions"]["mode"] == "bypass"
    data = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert data["permissions"]["mode"] == "bypass"
    assert data["permissions"]["deny_paths"] == ["secrets/"]
    assert data["agent"]["max_turns"] == 7
    """The sections the page does not know about stay as they are."""


def test_the_api_never_writes_the_project_file(make_client, tmp_path):
    client = make_client()

    client.put("/api/config/permissions", json={"mode": "bypass"})

    assert "bypass" not in (tmp_path / ".coderagent" / "config.yaml").read_text(encoding="utf-8")


def test_a_new_session_picks_the_new_mode_up(make_client):
    client = make_client()
    client.put("/api/config/permissions", json={"mode": "readonly"})

    session_id = client.post("/api/sessions").json()["id"]

    assert client.get(f"/api/sessions/{session_id}/status").json()["mode"] == "readonly"
    """The files are read again for every session, so the new mode is there."""


def test_the_mode_of_a_running_session_changes_at_once(make_client, send, wait_for):
    client = make_client(responses=[assistant("done")])
    session_id = client.post("/api/sessions").json()["id"]
    send(client, session_id, "say hello")
    wait_for(client, session_id, "turn_end")

    response = client.post(f"/api/sessions/{session_id}/mode", json={"mode": "readonly"})

    assert response.status_code == 200
    assert response.json()["mode"] == "readonly"
    assert client.get(f"/api/sessions/{session_id}/status").json()["mode"] == "readonly"
    """The policy is changed in place: the session does not have to be rebuilt."""


def test_the_mode_of_a_session_that_has_not_run_yet_changes(make_client):
    client = make_client()
    session_id = client.post("/api/sessions").json()["id"]

    client.post(f"/api/sessions/{session_id}/mode", json={"mode": "bypass"})

    assert client.get(f"/api/sessions/{session_id}/status").json()["mode"] == "bypass"
    """The mode of a session without a loop is the one it will be started with."""


def test_an_unknown_mode_is_refused_with_400(make_client):
    client = make_client()
    session_id = client.post("/api/sessions").json()["id"]

    assert client.post(f"/api/sessions/{session_id}/mode", json={"mode": "turbo"}).status_code == 400
    assert client.put("/api/config/permissions", json={"mode": "turbo"}).status_code == 400


def test_the_server_mode_is_reported_as_pinned(make_client):
    client = make_client(permission_mode="bypass")
    client.put("/api/config/permissions", json={"mode": "readonly"})

    permissions = client.get("/api/config").json()["permissions"]

    assert permissions["server_mode"] == "bypass"
    assert permissions["mode"] == "bypass"
    assert permissions["source"]["mode"] == "server"
    """The file does not decide the mode when the server was started with one."""
