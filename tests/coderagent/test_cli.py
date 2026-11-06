import json

from typer.testing import CliRunner

from coderagent.config.loader import load_config
from coderagent.core.session import SessionStore
from coderagent.testing.scripted_model import ScriptedModel
from coderagent.ui.cli import app, main_impl


def _config(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    return load_config([], cwd=tmp_path)


def test_json_output_contains_session_and_messages(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    model = ScriptedModel([{"role": "assistant", "content": "hello", "tool_calls": [], "extra": {"cost": 0.1}}])
    output = main_impl("hi", config, tmp_path, "json", model=model, store=SessionStore(tmp_path))
    payload = json.loads(output)
    assert payload["messages"][0] == {"role": "user", "content": "hi"}
    assert payload["messages"][1]["content"] == "hello"
    assert payload["cost"] == 0.1
    assert payload["stop_reason"] == "end_turn"
    assert payload["error"] == ""
    assert payload["session_id"]


def test_error_is_visible_in_the_output(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    model = ScriptedModel([])
    output = main_impl("hi", config, tmp_path, "text", model=model, store=SessionStore(tmp_path))
    assert "[error]" in output
    assert "ran out of responses" in output


def test_text_output_shows_the_assistant_message(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    model = ScriptedModel([{"role": "assistant", "content": "hello", "tool_calls": [], "extra": {"cost": 0.0}}])
    output = main_impl("hi", config, tmp_path, "text", model=model, store=SessionStore(tmp_path))
    assert "hello" in output
    assert "stop_reason=end_turn" in output


def test_help_is_available():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--output-format" in result.output


def test_the_sessions_of_the_directory_are_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    store = SessionStore(tmp_path / "home" / "sessions")
    session = store.create(tmp_path)
    result = CliRunner().invoke(app, ["--list", "--cwd", str(tmp_path)])
    assert result.exit_code == 0
    assert session.id in result.output


def test_a_session_can_be_resumed(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    store = SessionStore(tmp_path / "home" / "sessions")
    session = store.create(tmp_path)
    result = CliRunner().invoke(app, ["--resume", session.id, "--cwd", str(tmp_path)])
    assert result.exit_code == 0
    assert session.id in result.output
