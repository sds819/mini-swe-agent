"""The tests of the eval harness: the task format and its parsing."""

import json
from pathlib import Path

import pytest

from coderagent.eval.task import load_suite, load_task, script_responses

TASK = """
id: off-by-one
prompt: Fix calc.py.
setup:
  - pip install -e .
verify:
  - python -m pytest -q tests/test_calc.py
timeout: 60
verify_timeout: 30
tags: [bugfix]
config:
  - agent.max_turns=20
script:
  - content: Looking.
    tool_calls:
      - tool: read
        args: {path: calc.py}
  - content: Fixed.
"""


def _suite(tmp_path: Path) -> Path:
    """A suite with two tasks and a file that is not a task."""
    for name in ("beta", "alpha"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "task.yaml").write_text(TASK.replace("id: off-by-one\n", ""), encoding="utf-8")
    (tmp_path / "README.md").write_text("not a task", encoding="utf-8")
    return tmp_path


def test_the_fields_of_the_task_are_read(tmp_path):
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "task.yaml").write_text(TASK, encoding="utf-8")
    task = load_task(directory)
    assert task.id == "off-by-one"
    assert task.prompt == "Fix calc.py."
    assert task.setup == ["pip install -e ."]
    assert task.verify == ["python -m pytest -q tests/test_calc.py"]
    assert task.timeout == 60
    assert task.verify_timeout == 30
    assert task.tags == ["bugfix"]
    assert task.config == ["agent.max_turns=20"]
    assert len(task.script) == 2


def test_the_id_is_the_name_of_the_directory(tmp_path):
    directory = tmp_path / "the-task"
    directory.mkdir()
    (directory / "task.yaml").write_text("prompt: hi\nverify:\n  - true\n", encoding="utf-8")
    assert load_task(directory).id == "the-task"


def test_a_task_without_a_task_file_is_an_error(tmp_path):
    directory = tmp_path / "empty"
    directory.mkdir()
    with pytest.raises(FileNotFoundError):
        load_task(directory)


def test_a_task_without_a_verify_command_is_an_error(tmp_path):
    """A task that cannot be checked would pass without doing anything."""
    directory = tmp_path / "no-verify"
    directory.mkdir()
    (directory / "task.yaml").write_text("prompt: hi\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_task(directory)


def test_a_task_that_must_fail_is_read(tmp_path):
    """A task that must fail keeps the suite honest."""
    directory = tmp_path / "guard"
    directory.mkdir()
    (directory / "task.yaml").write_text("prompt: hi\nverify:\n  - false\nexpect: fail\n", encoding="utf-8")
    assert load_task(directory).expect == "fail"


def test_an_expectation_that_is_neither_pass_nor_fail_is_an_error(tmp_path):
    directory = tmp_path / "strange"
    directory.mkdir()
    (directory / "task.yaml").write_text("prompt: hi\nverify:\n  - true\nexpect: maybe\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_task(directory)


def test_the_requirements_of_the_task_are_read(tmp_path):
    """A requirement names the tools that have to work, and the files they have to touch."""
    directory = tmp_path / "the-task"
    directory.mkdir()
    (directory / "task.yaml").write_text(
        "prompt: hi\nverify:\n  - true\nrequire_tools:\n  - tools: [edit, multi_edit]\n    paths: [calc.py]\n",
        encoding="utf-8",
    )
    task = load_task(directory)
    assert len(task.require_tools) == 1
    assert task.require_tools[0].tools == ["edit", "multi_edit"]
    assert task.require_tools[0].paths == ["calc.py"]


def test_a_requirement_may_be_the_name_of_a_tool_alone(tmp_path):
    directory = tmp_path / "the-task"
    directory.mkdir()
    (directory / "task.yaml").write_text("prompt: hi\nverify:\n  - true\nrequire_tools:\n  - edit\n", encoding="utf-8")
    task = load_task(directory)
    assert task.require_tools[0].tools == ["edit"]
    assert task.require_tools[0].paths == []


def test_a_requirement_without_a_tool_is_an_error(tmp_path):
    """A requirement that names no tool says nothing."""
    directory = tmp_path / "the-task"
    directory.mkdir()
    (directory / "task.yaml").write_text(
        "prompt: hi\nverify:\n  - true\nrequire_tools:\n  - paths: [calc.py]\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_task(directory)


def test_the_tasks_of_a_suite_are_sorted_and_the_files_ignored(tmp_path):
    tasks = load_suite(_suite(tmp_path))
    assert [task.id for task in tasks] == ["alpha", "beta"]
    assert [task.path.name for task in tasks] == ["alpha", "beta"]


def test_the_script_becomes_the_shape_of_the_model(tmp_path):
    responses = script_responses(load_task(_suite(tmp_path) / "alpha"))
    assert len(responses) == 2
    assert responses[0]["role"] == "assistant"
    assert responses[0]["content"] == "Looking."
    call = responses[0]["tool_calls"][0]
    assert call["id"] == "call_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "read"
    assert json.loads(call["function"]["arguments"]) == {"path": "calc.py"}
    assert "tool_calls" not in responses[1]


def test_the_ids_of_the_calls_are_unique(tmp_path):
    directory = tmp_path / "two-calls"
    directory.mkdir()
    (directory / "task.yaml").write_text(
        "prompt: hi\nverify:\n  - true\n"
        "script:\n"
        "  - content: one\n"
        "    tool_calls:\n"
        "      - tool: read\n"
        "        args: {path: a}\n"
        "      - tool: read\n"
        "        args: {path: b}\n",
        encoding="utf-8",
    )
    calls = script_responses(load_task(directory))[0]["tool_calls"]
    assert [call["id"] for call in calls] == ["call_1", "call_2"]
