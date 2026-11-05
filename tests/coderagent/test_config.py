import pytest
from pydantic import ValidationError

from coderagent.config.loader import load_config
from coderagent.config.schema import Config


def test_defaults_are_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    config = load_config([], cwd=tmp_path)
    assert config.model.model_name == "anthropic/claude-sonnet-4-5"
    assert config.agent.max_turns == 50
    assert config.tools.enabled == ["bash"]
    assert config.sandbox.type == "local"


def test_project_config_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    project = tmp_path / ".coderagent" / "config.yaml"
    project.parent.mkdir(parents=True)
    project.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")
    assert load_config([], cwd=tmp_path).agent.max_turns == 7


def test_user_config_overrides_project_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MSWEA_CODER_HOME", str(home))
    project = tmp_path / ".coderagent" / "config.yaml"
    project.parent.mkdir(parents=True)
    project.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")
    (home / "config.yaml").write_text("agent:\n  max_turns: 9\n", encoding="utf-8")
    assert load_config([], cwd=tmp_path).agent.max_turns == 9


def test_cli_spec_overrides_everything(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MSWEA_CODER_HOME", str(home))
    (home / "config.yaml").write_text("agent:\n  max_turns: 9\n", encoding="utf-8")
    config = load_config(["agent.max_turns=3"], cwd=tmp_path)
    assert config.agent.max_turns == 3
    assert config.agent.cost_limit == 0.0


def test_key_value_spec_can_set_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    config = load_config(["model.model_name=openai/gpt-5"], cwd=tmp_path)
    assert config.model.model_name == "openai/gpt-5"


def test_invalid_value_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
    with pytest.raises(ValidationError):
        load_config(["agent.max_turns=not-a-number"], cwd=tmp_path)


def test_config_defaults_are_valid():
    assert Config().tools.bash_timeout == 120
