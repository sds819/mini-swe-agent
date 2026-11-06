import json

import pytest

from coderagent.core.tokens import count_text_tokens, estimate_tokens, trim_lines, trim_text


def _messages(text: str, count: int = 1) -> list[dict]:
    return [{"role": "user", "content": text}] * count


def test_the_estimate_grows_with_the_conversation():
    small = estimate_tokens(_messages("hello"))
    large = estimate_tokens(_messages("hello" * 100))
    assert small < large


def test_the_tool_schemas_count_towards_the_estimate():
    messages = _messages("hello")
    tools = [{"type": "function", "function": {"name": "bash", "description": "x" * 500}}]
    assert estimate_tokens(messages, tools) > estimate_tokens(messages)


def test_tool_calls_are_part_of_the_estimate():
    with_calls = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "bash", "arguments": json.dumps({"command": "ls -la"})}}],
        }
    ]
    assert estimate_tokens(with_calls) > estimate_tokens(_messages(""))


def test_the_heuristic_is_close_to_the_exact_count():
    tiktoken = pytest.importorskip("tiktoken")
    encoding = tiktoken.get_encoding("cl100k_base")
    sample = "def add(a, b):\n    return a + b  # a small python function\n" * 20
    exact = len(encoding.encode(sample))
    estimate = int(len(sample) / 3.6)
    assert abs(estimate - exact) / exact < 0.2


def test_counting_text_tokens_is_positive():
    assert count_text_tokens("hello world") > 0


def test_short_text_is_not_trimmed():
    text, info = trim_text("hello", 1000)
    assert text == "hello"
    assert info == {}


def test_long_text_keeps_the_head_and_the_tail():
    text, info = trim_text("a" * 5000 + "b" * 5000, 100)
    assert info["elided_characters"] > 0
    assert text.startswith("a")
    assert text.endswith("b")
    assert "tokens elided" in text


def test_long_line_lists_keep_the_head_and_the_tail():
    lines = [f"line{i}" for i in range(500)]
    trimmed, info = trim_lines(lines, 50)
    assert info["elided_lines"] > 0
    assert trimmed[0] == "line0"
    assert trimmed[-1] == "line499"
    assert any("lines elided" in line for line in trimmed)


def test_short_line_lists_are_not_trimmed():
    lines = ["one", "two"]
    trimmed, info = trim_lines(lines, 1000)
    assert trimmed == lines
    assert info == {}
