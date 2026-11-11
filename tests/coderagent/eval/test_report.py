"""The tests of the report of an eval run: the numbers, the fingerprint and the text."""

import json

from coderagent.config.loader import load_config
from coderagent.eval.report import FORMAT, Report, fingerprint, fingerprint_inputs
from coderagent.eval.runner import TaskResult


def _report(tmp_path, **kwargs) -> Report:
    config = load_config([], cwd=tmp_path)
    model = config.model.model_name
    return Report(
        label="live-1",
        suite="evals/basic",
        model=model,
        fingerprint=fingerprint(config, model),
        config=fingerprint_inputs(config, model),
        started_at=1762830000.0,
        duration_seconds=41.2,
        tasks=[
            TaskResult(id="off-by-one", mode="live", passed=True, stop_reason="end_turn", cost=0.012, model_calls=7),
            TaskResult(id="create-file", mode="live", passed=False, stop_reason="max_turns", error="the agent stopped"),
        ],
        **kwargs,
    )


def test_the_fingerprint_follows_the_system_prompt(tmp_path):
    """A change of the harness must be visible in the numbers."""
    config = load_config([], cwd=tmp_path)
    before = fingerprint(config, config.model.model_name)
    config.agent.system_prompt = "Another prompt."
    assert fingerprint(config, config.model.model_name) != before


def test_the_fingerprint_does_not_depend_on_the_time(tmp_path):
    config = load_config([], cwd=tmp_path)
    assert fingerprint(config, config.model.model_name) == fingerprint(config, config.model.model_name)


def test_the_fingerprint_follows_the_permission_mode(tmp_path):
    config = load_config([], cwd=tmp_path)
    assert fingerprint(config, config.model.model_name, "default") != fingerprint(
        config, config.model.model_name, "bypass"
    )


def test_the_json_report_can_be_read(tmp_path):
    data = _report(tmp_path).to_dict()
    assert data["format"] == FORMAT == "coder-eval-1.0"
    assert json.loads(json.dumps(data))["summary"]["tasks"] == 2
    assert data["summary"]["passed"] == 1
    assert data["summary"]["failed"] == 1
    assert data["summary"]["pass_rate"] == 0.5
    assert data["tasks"][0]["id"] == "off-by-one"


def test_the_tasks_of_the_harness_are_not_graded(tmp_path):
    """A task whose setup failed says nothing about the agent."""
    report = _report(tmp_path)
    report.tasks.append(TaskResult(id="broken", mode="live", passed=False, error_kind="setup"))
    assert report.summary["errors"] == 1
    assert report.summary["pass_rate"] == 0.5


def test_the_text_report_shows_the_tasks_and_the_totals(tmp_path):
    text = _report(tmp_path).to_text()
    assert "off-by-one" in text
    assert "create-file" in text
    assert "✓" in text
    assert "✗" in text
    assert "2 tasks: 1 passed, 1 failed, 0 errors" in text
