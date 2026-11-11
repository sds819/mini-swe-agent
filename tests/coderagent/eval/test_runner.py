"""The tests of the runner of the eval harness: the tasks, the isolation, the metrics."""

import subprocess
from pathlib import Path

import yaml

from coderagent.config.loader import load_config
from coderagent.core.events import EventType
from coderagent.core.session import SessionStore
from coderagent.eval.runner import run_task
from coderagent.eval.task import Task, load_task

REPO = Path(__file__).parents[3]

CALC = "def add_one(n):\n    return n + 2\n"
TEST = "from calc import add_one\n\n\ndef test_add_one():\n    assert add_one(1) == 2\n"


def _task(
    tmp_path: Path,
    script: list[dict],
    files: dict[str, str] | None = None,
    *,
    verify: list[str] | None = None,
    timeout: int = 300,
) -> Task:
    """A task on the disk, with its fixture."""
    directory = tmp_path / "the-task"
    directory.mkdir(exist_ok=True)
    for name, content in (files or {}).items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (directory / "task.yaml").write_text(
        yaml.safe_dump({"prompt": "Do it.", "verify": verify or ["true"], "script": script, "timeout": timeout}),
        encoding="utf-8",
    )
    return load_task(directory)


def _run(task: Task, tmp_path: Path, permission_mode: str = "bypass"):
    config = load_config([], cwd=tmp_path)
    store = SessionStore(tmp_path / "home" / "sessions")
    result = run_task(
        task,
        config,
        workdir=tmp_path / "work",
        store=store,
        permission_mode=permission_mode,
        user_home=tmp_path / "home",
    )
    return result, store


def _scripted_fix() -> list[dict]:
    return [
        {"content": "Looking at the file.", "tool_calls": [{"tool": "read", "args": {"path": "calc.py"}}]},
        {
            "content": "Fixing it.",
            "tool_calls": [
                {
                    "tool": "edit",
                    "args": {"path": "calc.py", "old_string": "return n + 2", "new_string": "return n + 1"},
                }
            ],
        },
        {"content": "The test passes."},
    ]


def test_a_scripted_task_that_fixes_the_bug_passes(tmp_path):
    task = _task(
        tmp_path,
        _scripted_fix(),
        {"calc.py": CALC, "tests/test_calc.py": TEST},
        verify=["python -m pytest -q tests/test_calc.py"],
    )
    result, _ = _run(task, tmp_path)
    assert result.passed is True
    assert result.stop_reason == "end_turn"
    assert result.mode == "scripted"
    assert result.model_calls == 3
    assert result.tool_calls == 2
    assert result.verify[0].exit_code == 0
    assert "return n + 1\n" in (tmp_path / "work" / "calc.py").read_text(encoding="utf-8")


def test_a_scripted_task_that_does_nothing_fails(tmp_path):
    task = _task(
        tmp_path,
        [{"content": "I am done."}],
        {"calc.py": CALC, "tests/test_calc.py": TEST},
        verify=["python -m pytest -q tests/test_calc.py"],
    )
    result, _ = _run(task, tmp_path)
    assert result.passed is False
    assert result.verify[0].exit_code != 0
    assert "failed" in result.verify[0].output
    assert "return n + 2" in (tmp_path / "work" / "calc.py").read_text(encoding="utf-8")


def test_a_script_that_runs_out_is_an_error_of_the_harness(tmp_path):
    """The script is too short. That is not the agent failing."""
    task = _task(tmp_path, [{"content": "Looking.", "tool_calls": [{"tool": "read", "args": {"path": "calc.py"}}]}])
    result, _ = _run(task, tmp_path)
    assert result.stop_reason == "error"
    assert "ran out of responses" in result.error
    assert result.error_kind == "script"
    assert result.passed is False


def test_the_run_does_not_touch_the_repository(tmp_path):
    before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
    task = _task(tmp_path, _scripted_fix(), {"calc.py": CALC, "tests/test_calc.py": TEST})
    _run(task, tmp_path)
    after = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
    assert after == before


def test_the_sessions_stay_in_the_home_of_the_run(tmp_path):
    task = _task(tmp_path, _scripted_fix(), {"calc.py": CALC, "tests/test_calc.py": TEST})
    result, store = _run(task, tmp_path)
    assert store.path(result.session_id).exists()
    assert store.path(result.session_id).parent == tmp_path / "home" / "sessions"


def test_the_task_stops_when_the_time_is_up(tmp_path):
    task = _task(
        tmp_path,
        [{"content": "Sleeping.", "tool_calls": [{"tool": "bash", "args": {"command": "sleep 2"}}]}],
        {"calc.py": CALC, "tests/test_calc.py": TEST},
        verify=["python -m pytest -q tests/test_calc.py"],
        timeout=1,
    )
    result, _ = _run(task, tmp_path)
    assert result.stop_reason == "interrupted"
    assert result.passed is False


def test_the_session_has_no_reflection(tmp_path):
    """The reflection of a session would eat a response of the script."""
    task = _task(tmp_path, _scripted_fix(), {"calc.py": CALC, "tests/test_calc.py": TEST})
    result, store = _run(task, tmp_path)
    events = store.events(result.session_id)
    assert [event for event in events if event.type == EventType.REFLECTION] == []
    assert result.model_calls == len(task.script)


def test_the_approvals_are_counted(tmp_path):
    """In the default mode the agent asks a human. The run counts the questions."""
    task = _task(
        tmp_path,
        [
            {
                "content": "Fixing.",
                "tool_calls": [{"tool": "edit", "args": {"path": "a.txt", "old_string": "x", "new_string": "y"}}],
            },
            {"content": "Done."},
        ],
        {"a.txt": "x"},
        verify=["grep -qx y a.txt"],
    )
    result, _ = _run(task, tmp_path, permission_mode="default")
    assert result.approvals == 1
    assert result.tool_errors == 0
    assert result.passed is True


def test_a_failing_tool_call_is_counted(tmp_path):
    task = _task(
        tmp_path,
        [
            {
                "content": "Editing.",
                "tool_calls": [{"tool": "edit", "args": {"path": "a.txt", "old_string": "zzz", "new_string": "y"}}],
            },
            {"content": "Done."},
        ],
        {"a.txt": "x"},
        verify=["grep -qx y a.txt"],
    )
    result, _ = _run(task, tmp_path)
    assert result.tool_errors == 1
    assert result.passed is False
