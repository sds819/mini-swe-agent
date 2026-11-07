"""The tests of the coding agent never touch the data of the user."""

import pytest


@pytest.fixture(autouse=True)
def _coder_home(tmp_path, monkeypatch):
    """The user level data goes to a temporary directory, not to the one of the user."""
    monkeypatch.setenv("MSWEA_CODER_HOME", str(tmp_path / "home"))
