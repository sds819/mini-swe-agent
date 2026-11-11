"""The tests of the suite that ships with the harness."""

import subprocess
from pathlib import Path

import pytest

from coderagent.eval.runner import prepare_workdir
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
