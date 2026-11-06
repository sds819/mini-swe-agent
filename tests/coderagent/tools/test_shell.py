import time

import pytest

from coderagent.testing.factory import build_context
from coderagent.tools.builtin.shell import BashKillTool, BashOutputTool, BashTool, CodingEnvironment, trim_output


@pytest.fixture
def ctx(tmp_path):
    return build_context(tmp_path)


def test_bash_returns_the_command_output(ctx):
    result = BashTool().run({"command": "echo hello"}, ctx)
    assert result.content.strip() == "hello"
    assert not result.is_error


def test_bash_reports_a_failing_command(ctx):
    result = BashTool().run({"command": "exit 3"}, ctx)
    assert result.is_error
    assert "exit code 3" in result.content


def test_bash_runs_in_the_working_directory(ctx, tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    assert "marker.txt" in BashTool().run({"command": "ls"}, ctx).content


def test_bash_kills_a_command_that_runs_too_long(ctx):
    started = time.time()
    result = BashTool().run({"command": "sleep 30", "timeout": 1}, ctx)
    assert time.time() - started < 10
    assert result.is_error
    assert "timed out" in result.content.lower() or "timeout" in result.content.lower()


def test_bash_trims_long_output(ctx):
    result = BashTool().run({"command": "for i in $(seq 1 20000); do echo 0123456789; done"}, ctx)
    assert "characters elided" in result.content


def test_trim_output_keeps_the_head_and_the_tail():
    trimmed = trim_output("a" * 100 + "b" * 100, 4)
    assert "characters elided" in trimmed
    assert trimmed.startswith("a")
    assert trimmed.endswith("b")


def test_bash_rejects_an_empty_command(ctx):
    assert BashTool().run({"command": "  "}, ctx).is_error


def test_the_coding_environment_ignores_the_submission_sentinel(tmp_path):
    env = CodingEnvironment(cwd=str(tmp_path))
    output = env.execute({"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"})
    assert output["returncode"] == 0
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in output["output"]


def test_a_background_task_can_be_read_and_killed(ctx):
    started = BashTool().run({"command": "sleep 30", "run_in_background": True}, ctx)
    task_id = started.metadata["task_id"]

    output = BashOutputTool().run({"task_id": task_id}, ctx)
    assert "running" in output.content

    assert "Killed" in BashKillTool().run({"task_id": task_id}, ctx).content
    assert "exited" in BashOutputTool().run({"task_id": task_id}, ctx).content


def test_the_background_tools_reject_unknown_tasks(ctx):
    assert BashOutputTool().run({"task_id": "nope"}, ctx).is_error
    assert BashKillTool().run({"task_id": "nope"}, ctx).is_error
