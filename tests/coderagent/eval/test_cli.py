"""The tests of the eval command."""

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from coderagent.ui.cli import app

SCRIPT = [
    {
        "content": "Writing the file.",
        "tool_calls": [{"tool": "write", "args": {"path": "hello.txt", "content": "hi\n"}}],
    },
    {"content": "Done."},
]


def _suite(tmp_path: Path) -> Path:
    """A suite with one task."""
    directory = tmp_path / "the-suite" / "write-hello"
    directory.mkdir(parents=True)
    (directory / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "prompt": "Write hello.txt.",
                "verify": ["grep -qx hi hello.txt"],
                "tags": ["feature"],
                "script": SCRIPT,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "the-suite"


def test_the_command_runs_the_suite(tmp_path):
    result = CliRunner().invoke(app, ["eval", str(_suite(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "write-hello" in result.output
    assert "1 tasks: 1 passed" in result.output


def test_the_json_report_is_printed(tmp_path):
    result = CliRunner().invoke(app, ["eval", str(_suite(tmp_path)), "--format", "json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["format"] == "coder-eval-1.0"
    assert report["summary"]["passed"] == 1
    assert report["tasks"][0]["id"] == "write-hello"
    assert report["tasks"][0]["mode"] == "scripted"
    assert report["fingerprint"].startswith("sha256:")


def test_the_report_is_written_to_the_file(tmp_path):
    out = tmp_path / "report.json"
    result = CliRunner().invoke(app, ["eval", str(_suite(tmp_path)), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["tasks"] == 1


def test_only_the_asked_tasks_run(tmp_path):
    suite = _suite(tmp_path)
    (suite / "other").mkdir()
    (suite / "other" / "task.yaml").write_text(
        yaml.safe_dump({"prompt": "Nothing.", "verify": ["true"], "tags": ["other"], "script": [{"content": "Ok."}]}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["eval", str(suite), "--only", "write-hello", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert [task["id"] for task in json.loads(result.output)["tasks"]] == ["write-hello"]


def test_the_tasks_are_filtered_by_tag(tmp_path):
    suite = _suite(tmp_path)
    (suite / "other").mkdir()
    (suite / "other" / "task.yaml").write_text(
        yaml.safe_dump({"prompt": "Nothing.", "verify": ["true"], "tags": ["other"], "script": [{"content": "Ok."}]}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["eval", str(suite), "--tag", "other", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert [task["id"] for task in json.loads(result.output)["tasks"]] == ["other"]


def test_the_run_directory_keeps_the_working_directories(tmp_path):
    run_dir = tmp_path / "the-run"
    result = CliRunner().invoke(app, ["eval", str(_suite(tmp_path)), "--run-dir", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert (run_dir / "work" / "write-hello" / "hello.txt").exists()
    assert list((run_dir / "home" / "sessions").glob("*.jsonl"))


def _report(path: Path, label: str, passed: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "label": label,
                "fingerprint": "sha256:x",
                "summary": {"tasks": 1, "passed": int(passed)},
                "tasks": [{"id": "write-hello", "passed": passed, "expect": "pass", "as_expected": passed}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_report_that_did_what_it_should_passes(tmp_path):
    after = _report(tmp_path / "after.json", "head", True)
    result = CliRunner().invoke(app, ["eval-compare", str(after)])
    assert result.exit_code == 0, result.output
    assert "problems" not in result.output


def test_a_report_with_a_task_that_failed_its_check_is_a_problem(tmp_path):
    after = _report(tmp_path / "after.json", "head", False)
    result = CliRunner().invoke(app, ["eval-compare", str(after)])
    assert result.exit_code == 1
    assert "did not do what they were supposed to do" in result.output


def test_a_task_that_stops_passing_is_a_regression(tmp_path):
    before = _report(tmp_path / "before.json", "base", True)
    after = _report(tmp_path / "after.json", "head", False)
    result = CliRunner().invoke(app, ["eval-compare", str(after), "--against", str(before)])
    assert result.exit_code == 1
    assert "regressions" in result.output
    assert "write-hello" in result.output


def test_the_comparison_can_be_read_as_json(tmp_path):
    before = _report(tmp_path / "before.json", "base", True)
    after = _report(tmp_path / "after.json", "head", True)
    result = CliRunner().invoke(app, ["eval-compare", str(after), "--against", str(before), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["regressions"] == []
