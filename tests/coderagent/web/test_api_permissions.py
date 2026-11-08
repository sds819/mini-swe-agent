"""The permission settings of the web interface: the files and the running session."""

import pytest
import yaml

pytest.importorskip("fastapi")

from coderagent.paths import config_home  # noqa: E402
from coderagent.web import config_api  # noqa: E402


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
