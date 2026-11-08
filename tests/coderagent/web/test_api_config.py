"""The model configuration page: the layers, the secrets and the write back."""

import pytest

pytest.importorskip("fastapi")

from coderagent.paths import config_home  # noqa: E402


@pytest.fixture(autouse=True)
def _no_model_in_the_environment(monkeypatch):
    """The environment of the user must not decide what the test expects."""
    monkeypatch.delenv("MSWEA_MODEL_NAME", raising=False)


def test_the_settings_are_written_to_the_user_file(make_client, tmp_path):
    client = make_client()
    user_file = config_home() / "config.yaml"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("agent:\n  max_turns: 7\n", encoding="utf-8")

    response = client.put(
        "/api/config/model",
        json={
            "model_name": "deepseek/deepseek-flash",
            "api_base": "https://api.deepseek.com",
            "api_key": "sk-secret-value",
            "max_retries": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["path"] == str(user_file)
    written = user_file.read_text(encoding="utf-8")
    assert "deepseek/deepseek-flash" in written
    assert "sk-secret-value" in written
    assert "max_turns: 7" in written
    """The sections the page does not know about stay as they are."""


def test_the_project_file_is_never_written(make_client, tmp_path):
    client = make_client()

    client.put("/api/config/model", json={"model_name": "deepseek/deepseek-flash"})

    assert "model_name" not in (tmp_path / ".coderagent" / "config.yaml").read_text(encoding="utf-8")


def test_the_key_never_leaves_the_server(make_client):
    client = make_client()
    client.put("/api/config/model", json={"model_name": "deepseek/deepseek-flash", "api_key": "sk-secret-value"})

    view = client.get("/api/config").json()["model"]

    assert view["api_key_set"] is True
    assert view["api_key_hint"].endswith("alue")
    assert "sk-secret-value" not in client.get("/api/config").text
    assert "sk-secret-value" not in client.get("/api/config").json()["layers"][0]["model"].get("model_kwargs", {})


def test_the_source_of_a_setting_is_the_layer_it_comes_from(make_client):
    client = make_client()

    before = client.get("/api/config").json()["sources"]
    client.put("/api/config/model", json={"model_name": "deepseek/deepseek-flash"})
    after = client.get("/api/config").json()["sources"]

    assert before["model_name"] == "defaults"
    assert after["model_name"] == "user"


def test_the_layers_are_shown_without_the_secrets(make_client):
    client = make_client()
    client.put("/api/config/model", json={"api_key": "sk-secret-value"})

    layers = client.get("/api/config").json()["layers"]
    names = [layer["layer"] for layer in layers]

    assert "defaults" in names
    assert "user" in names
    assert all(
        value != "sk-secret-value"
        for layer in layers
        for value in (layer["model"].get("model_kwargs") or {}).values()
    )


def test_a_model_that_does_not_work_is_reported_not_raised(make_client):
    client = make_client()

    response = client.post("/api/config/model/test", json={"model_name": "not-a-real-provider/nope"})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"]
