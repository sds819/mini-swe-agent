"""The tests of the comparison of two eval reports."""

import json

from coderagent.eval.compare import check, compare, render, verdict


def _report(label: str, fingerprint: str, tasks: list[dict]) -> dict:
    return {"label": label, "fingerprint": fingerprint, "tasks": tasks, "summary": {"tasks": len(tasks)}}


def _task(task_id: str, passed: bool, expect: str = "pass", as_expected: bool = True) -> dict:
    return {"id": task_id, "passed": passed, "expect": expect, "as_expected": as_expected}


def test_a_task_that_stops_passing_is_a_regression():
    before = _report("base", "sha256:a", [_task("one", True), _task("two", True)])
    after = _report("head", "sha256:b", [_task("one", True), _task("two", False)])
    comparison = compare(before, after)
    assert comparison.regressions == ["two"]
    assert comparison.improvements == []
    assert comparison.before_pass_rate == 1.0
    assert comparison.after_pass_rate == 0.5
    assert comparison.drop == 0.5
    assert comparison.config_changed


def test_a_task_that_starts_passing_is_an_improvement():
    before = _report("base", "sha256:a", [_task("one", False)])
    after = _report("head", "sha256:a", [_task("one", True)])
    comparison = compare(before, after)
    assert comparison.improvements == ["one"]
    assert comparison.regressions == []
    assert not comparison.config_changed


def test_a_task_of_only_one_run_is_not_compared():
    before = _report("base", "sha256:a", [_task("one", True)])
    after = _report("head", "sha256:b", [_task("one", True), _task("two", False)])
    comparison = compare(before, after)
    assert comparison.compared == ["one"]
    assert comparison.only_after == ["two"]
    assert comparison.only_before == []
    assert comparison.regressions == []


def test_a_task_that_must_fail_is_not_a_rate():
    """It keeps the suite honest, it is not a task the agent can pass."""
    before = _report("base", "sha256:a", [_task("one", True), _task("guard", False, "fail")])
    after = _report("head", "sha256:a", [_task("one", True), _task("guard", False, "fail")])
    comparison = compare(before, after)
    assert comparison.before_pass_rate == 1.0
    assert comparison.after_pass_rate == 1.0
    assert comparison.regressions == []
    assert comparison.graded == ["one"]


def test_the_expectation_of_the_newer_run_wins():
    """The reports of the old harness have no field, the newer run decides."""
    before = _report("base", "sha256:a", [{"id": "guard", "passed": False}])
    after = _report("head", "sha256:b", [_task("guard", False, "fail")])
    comparison = compare(before, after)
    assert comparison.before_pass_rate == 0.0
    assert comparison.after_pass_rate == 0.0
    assert comparison.regressions == []


def test_the_verdict_names_the_regressions():
    before = _report("base", "sha256:a", [_task("one", True)])
    after = _report("head", "sha256:b", [_task("one", False)])
    problems = verdict(compare(before, after))
    assert len(problems) == 2
    assert "one" in problems[0]
    assert "pass rate" in problems[1]


def test_the_verdict_forgives_what_is_allowed():
    before = _report("base", "sha256:a", [_task("one", True), _task("two", True)])
    after = _report("head", "sha256:b", [_task("one", False), _task("two", True)])
    assert verdict(compare(before, after))
    assert not verdict(compare(before, after), max_regressions=1, max_drop=0.5)


def test_a_run_that_did_not_do_what_it_should_is_a_problem():
    report = _report("head", "sha256:a", [_task("one", False, as_expected=False)])
    problems = check(report)
    assert len(problems) == 1
    assert "one" in problems[0]


def test_a_task_the_harness_could_not_grade_is_a_problem():
    report = _report("head", "sha256:a", [{"id": "one", "passed": False, "error_kind": "setup"}])
    assert check(report)


def test_the_comparison_is_readable():
    before = _report("base", "sha256:a", [_task("one", True)])
    after = _report("head", "sha256:b", [_task("one", False)])
    text = render(compare(before, after))
    assert "the configuration changed between the two runs" in text
    assert "regressions: one" in text
    assert "pass rate: 1.000 -> 0.000" in text


def test_the_comparison_names_the_guards():
    """A task that must fail is not a rate, the text says which one it is."""
    before = _report("base", "sha256:a", [_task("one", True), _task("guard", False, "fail")])
    after = _report("head", "sha256:a", [_task("one", True), _task("guard", False, "fail")])
    text = render(compare(before, after))
    assert "pass rate: 1.000 -> 1.000 over 1 tasks of both runs" in text
    assert "guards: guard" in text


def test_the_comparison_can_be_written_as_json():
    """The reports are json, the comparison of two of them is too."""
    before = json.dumps(_report("base", "sha256:a", [_task("one", True)]))
    after = json.dumps(_report("head", "sha256:b", [_task("one", False)]))
    assert compare(json.loads(before), json.loads(after)).regressions == ["one"]
