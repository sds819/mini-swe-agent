"""The tests of the suites that ship with the harness."""

import subprocess
from pathlib import Path

import pytest

from coderagent.config.loader import load_config
from coderagent.core.session import SessionStore
from coderagent.eval.runner import prepare_workdir, run_suite
from coderagent.eval.task import load_suite

SUITE = Path(__file__).parents[3] / "evals" / "basic"
IDS = [
    "cli-flag",
    "config-value",
    "create-file",
    "grep-count",
    "import-error",
    "no-op",
    "off-by-one",
    "rename-symbol",
]
"""The tasks of the suite, in the order they are sorted."""

OFFLINE = Path(__file__).parents[3] / "evals" / "offline"
OFFLINE_IDS = ["bash-command", "broken-check", "edit-file", "read-only", "write-file"]
"""The tasks of the suite that needs no API key."""


def test_the_suite_holds_the_tasks_it_should():
    assert [task.id for task in load_suite(SUITE)] == IDS


@pytest.mark.parametrize("task_id", [task_id for task_id in IDS if task_id != "no-op"])
def test_a_task_is_not_solved_before_the_agent_starts(task_id, tmp_path):
    """Otherwise the agent would pass by doing nothing."""
    task = next(task for task in load_suite(SUITE) if task.id == task_id)
    workdir = prepare_workdir(task, tmp_path / task_id)
    results = [subprocess.run(command, shell=True, cwd=workdir) for command in task.verify]
    assert any(result.returncode != 0 for result in results)


def test_the_no_op_task_is_satisfied_from_the_start(tmp_path):
    """Its check passes before the agent does anything: the agent must not break what is fine."""
    task = next(task for task in load_suite(SUITE) if task.id == "no-op")
    workdir = prepare_workdir(task, tmp_path / "no-op")
    results = [subprocess.run(command, shell=True, cwd=workdir) for command in task.verify]
    assert all(result.returncode == 0 for result in results)


def test_the_offline_suite_needs_no_api_key(tmp_path):
    """Every task of it is scripted, so the run never calls a model."""
    assert [task.id for task in load_suite(OFFLINE)] == OFFLINE_IDS
    assert all(task.script for task in load_suite(OFFLINE))


def test_the_offline_suite_does_what_it_should(tmp_path):
    """The harness works, and the check of the suite is able to fail."""
    config = load_config([], cwd=tmp_path)
    store = SessionStore(tmp_path / "home" / "sessions")
    results = run_suite(
        load_suite(OFFLINE),
        config,
        root=tmp_path / "work",
        store=store,
        user_home=tmp_path / "home",
    )
    assert [result.id for result in results] == OFFLINE_IDS
    assert all(result.as_expected for result in results)
    assert [result.id for result in results if result.passed] == [
        "bash-command",
        "edit-file",
        "read-only",
        "write-file",
    ]
