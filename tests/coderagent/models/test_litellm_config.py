"""The aliases of a litellm config file name the models."""

from coderagent.models.backends import LiteLLMBackend
from coderagent.models.litellm_config import deployments, resolve

CONFIG = """
model_list:
  - model_name: nengpa/minimax-m2.7
    litellm_params:
      model: openai/MiniMax-M2.7
      api_base: https://api.nengpa.com/v1
      api_key: sk-cp-secret
"""


def _write(tmp_path, content: str = CONFIG) -> str:
    path = tmp_path / "litellm_config.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_an_alias_names_the_model_and_its_parameters(tmp_path):
    assert resolve(_write(tmp_path), "nengpa/minimax-m2.7") == (
        "openai/MiniMax-M2.7",
        {"api_base": "https://api.nengpa.com/v1", "api_key": "sk-cp-secret"},
    )


def test_a_name_that_is_not_an_alias_stays_as_it_is(tmp_path):
    assert resolve(_write(tmp_path), "openai/gpt-4o") == ("openai/gpt-4o", {})


def test_a_file_that_is_not_there_has_no_aliases(tmp_path):
    assert resolve(str(tmp_path / "nope.yaml"), "nengpa/minimax-m2.7") == ("nengpa/minimax-m2.7", {})
    assert deployments(str(tmp_path / "nope.yaml")) == {}


def test_no_file_at_all_has_no_aliases():
    assert resolve("", "nengpa/minimax-m2.7") == ("nengpa/minimax-m2.7", {})


def test_the_backend_takes_the_model_and_the_key_from_the_alias(tmp_path):
    backend = LiteLLMBackend("nengpa/minimax-m2.7", litellm_config=_write(tmp_path))
    assert backend.model_name == "openai/MiniMax-M2.7"
    assert backend.model_kwargs == {"api_base": "https://api.nengpa.com/v1", "api_key": "sk-cp-secret"}


def test_the_settings_of_the_configuration_win_over_the_alias(tmp_path):
    backend = LiteLLMBackend(
        "nengpa/minimax-m2.7",
        model_kwargs={"api_key": "sk-other"},
        litellm_config=_write(tmp_path),
    )
    assert backend.model_kwargs == {"api_base": "https://api.nengpa.com/v1", "api_key": "sk-other"}
