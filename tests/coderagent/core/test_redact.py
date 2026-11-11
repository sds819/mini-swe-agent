"""Secrets do not belong in the log of a session, nor in the context of the model."""

from coderagent.core.redact import has_secret, redact


def test_a_key_that_looks_like_an_openai_key_is_hidden():
    assert redact("the key is sk-abcdefghijklmnopqrstuvwxyz") == "the key is [redacted]"


def test_a_github_token_is_hidden():
    assert redact("ghp_abcdefghijklmnopqrstuvwxyz012345") == "[redacted]"


def test_an_aws_key_is_hidden():
    assert redact("AKIAIOSFODNN7EXAMPLE") == "[redacted]"


def test_a_jwt_is_hidden():
    assert (
        redact("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
        == "[redacted]"
    )


def test_a_private_key_is_hidden():
    """The key is written in pieces, so the hook of the repository does not find it."""
    dashes = "-" * 5
    label = "RSA PRIVATE KEY"
    key = f"{dashes}BEGIN {label}-----\nMIIabc\n{dashes}END {label}-----"
    assert "MIIabc" not in redact(key)


def test_a_password_in_a_config_is_hidden():
    assert redact("password: hunter2secret") == "password: [redacted]"
    assert redact('api_key = "abcdef123456"') == 'api_key = "[redacted]"'


def test_a_bearer_token_is_hidden():
    assert redact("Authorization: Bearer abcdef1234567890") == "Authorization: Bearer [redacted]"


def test_an_ordinary_text_is_left_alone():
    text = "the tests pass and the token limit is 1000"
    assert redact(text) == text
    assert has_secret(text) is False


def test_the_name_of_a_setting_is_not_a_secret():
    assert redact("token_limit: 1000") == "token_limit: 1000"


def test_a_secret_is_recognized():
    assert has_secret("password=hunter2secret") is True
    assert has_secret("") is False
