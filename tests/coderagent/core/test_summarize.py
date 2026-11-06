"""The summary is a fixed structure, not free text."""

from coderagent.core.summarize import (
    Summary,
    conservative_summary,
    parse_summary,
    recent_errors,
    summarize_prompt,
)


def test_parse_summary_reads_every_field():
    summary = parse_summary(
        """Here you go:
```json
{
  "goal": "fix the parser",
  "findings": ["src/parse.py:10 raises on empty input"],
  "decisions": ["return None instead of raising"],
  "files_touched": [{"path": "src/parse.py", "change": "guard the empty case", "state": "modified"}],
  "open_questions": ["is None the right sentinel?"],
  "next_steps": ["add a test for the empty input"],
  "errors_seen": ["KeyError: 'x'"]
}
```"""
    )
    assert summary is not None
    assert summary.goal == "fix the parser"
    assert summary.findings == ["src/parse.py:10 raises on empty input"]
    assert summary.decisions == ["return None instead of raising"]
    assert summary.files_touched == [{"path": "src/parse.py", "change": "guard the empty case", "state": "modified"}]
    assert summary.open_questions == ["is None the right sentinel?"]
    assert summary.next_steps == ["add a test for the empty input"]
    assert summary.errors_seen == ["KeyError: 'x'"]


def test_parse_summary_rejects_unusable_answers():
    assert parse_summary("") is None
    assert parse_summary("I could not summarize that.") is None
    assert parse_summary('{"goal": ') is None
    assert parse_summary("[1, 2, 3]") is None


def test_parse_summary_ignores_unknown_and_wrongly_typed_fields():
    summary = parse_summary('{"goal": 5, "findings": "not a list", "files_touched": ["not a dict"], "extra": 1}')
    assert summary == Summary()


def test_parse_summary_drops_a_trailing_brace_of_the_chatty_part():
    summary = parse_summary('{"goal": "g", "note": "the answer is }"}')
    assert summary is None or summary.goal == "g"


def test_render_contains_every_field():
    rendered = Summary(
        goal="ship the feature",
        findings=["found a bug in a.py:3"],
        decisions=["use jsonl"],
        files_touched=[{"path": "a.py", "change": "fixed", "state": "modified"}],
        open_questions=["what about windows?"],
        next_steps=["write the test"],
        errors_seen=["boom"],
        recent_errors=["Error: boom"],
    ).render()
    assert rendered.startswith("<session_summary>")
    assert rendered.endswith("</session_summary>")
    for fragment in (
        "ship the feature",
        "found a bug in a.py:3",
        "use jsonl",
        "a.py (modified): fixed",
        "what about windows?",
        "write the test",
        "boom",
    ):
        assert fragment in rendered


def test_to_dict_round_trip():
    summary = Summary(goal="g", findings=["f"], files_touched=[{"path": "a", "change": "c", "state": "modified"}])
    assert Summary.from_dict(summary.to_dict()) == summary


def test_conservative_summary_keeps_the_last_messages_and_a_next_step():
    messages = [{"role": "user", "content": f"message {index}"} for index in range(10)]
    summary = conservative_summary(messages)
    assert len(summary.findings) == 5
    assert summary.findings[-1] == "user: message 9"
    assert summary.next_steps


def test_conservative_summary_of_nothing_is_still_usable():
    summary = conservative_summary([])
    assert summary.goal
    assert summary.findings == []
    assert summary.next_steps


def test_recent_errors_keeps_the_last_errors_only():
    messages = [{"role": "tool", "content": f"Error: failure {index}"} for index in range(6)] + [
        {"role": "tool", "content": "all good"}
    ]
    assert recent_errors(messages) == [
        "Error: failure 3",
        "Error: failure 4",
        "Error: failure 5",
    ]


def test_recent_errors_ignores_normal_output():
    assert recent_errors([{"role": "tool", "content": "file not found"}]) == []


def test_summarize_prompt_contains_the_transcript_and_the_tool_calls():
    prompt = summarize_prompt(
        [
            {"role": "user", "content": "fix it"},
            {
                "role": "assistant",
                "content": "on it",
                "tool_calls": [{"function": {"name": "edit", "arguments": '{"path": "a.py"}'}}],
            },
        ]
    )
    assert "fix it" in prompt
    assert "on it" in prompt
    assert "tool call edit" in prompt
    assert "a.py" in prompt
