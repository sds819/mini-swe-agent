import pytest

from coderagent.tools.permissions import PermissionMode, PermissionPolicy, Rule, glob_to_regex


def test_the_default_mode_allows_reads_and_asks_for_everything_else(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [], cwd=tmp_path)
    assert policy.check("read", {"path": "a.py"}) == "allow"
    assert policy.check("glob", {"pattern": "*"}) == "allow"
    assert policy.check("write", {"path": "a.py"}) == "ask"
    assert policy.check("edit", {"path": "a.py"}) == "ask"
    assert policy.check("bash", {"command": "ls"}) == "ask"


def test_accept_edits_allows_file_writes_but_asks_for_bash(tmp_path):
    policy = PermissionPolicy(PermissionMode.ACCEPT_EDITS, [], cwd=tmp_path)
    assert policy.check("edit", {"path": "a.py"}) == "allow"
    assert policy.check("write", {"path": "a.py"}) == "allow"
    assert policy.check("bash", {"command": "ls"}) == "ask"


@pytest.mark.parametrize("mode", [PermissionMode.PLAN, PermissionMode.READONLY])
def test_plan_and_readonly_deny_every_write(tmp_path, mode):
    policy = PermissionPolicy(mode, [], cwd=tmp_path)
    assert policy.check("read", {"path": "a.py"}) == "allow"
    assert policy.check("write", {"path": "a.py"}) == "deny"
    assert policy.check("bash", {"command": "ls"}) == "deny"


def test_bypass_allows_everything(tmp_path):
    policy = PermissionPolicy(PermissionMode.BYPASS, [], cwd=tmp_path)
    assert policy.check("bash", {"command": "rm -rf /"}) == "allow"
    assert policy.check("write", {"path": "a.py"}) == "allow"


def test_the_last_matching_rule_wins(tmp_path):
    rules = [
        Rule(tool="bash", pattern="git status", decision="allow"),
        Rule(tool="bash", pattern="git .*", decision="deny"),
    ]
    policy = PermissionPolicy(PermissionMode.DEFAULT, rules, cwd=tmp_path)
    assert policy.check("bash", {"command": "git status"}) == "deny"


def test_a_deny_rule_can_be_overridden_by_a_later_allow(tmp_path):
    rules = [
        Rule(tool="write", pattern="**/secrets/**", decision="deny"),
        Rule(tool="write", pattern="**/secrets/**", decision="allow", reason="explicitly allowed"),
    ]
    policy = PermissionPolicy(PermissionMode.DEFAULT, rules, cwd=tmp_path)
    assert policy.check("write", {"path": "secrets/key.txt"}) == "allow"


def test_path_rules_are_matched_against_the_path_relative_to_the_working_directory(tmp_path):
    policy = PermissionPolicy(
        PermissionMode.DEFAULT, [Rule(tool="write", pattern="**/tmp/**", decision="allow")], cwd=tmp_path
    )
    assert policy.check("write", {"path": "tmp/a.txt"}) == "allow"
    assert policy.check("write", {"path": "other/a.txt"}) == "ask"


def test_bash_rules_are_matched_as_regular_expressions(tmp_path):
    policy = PermissionPolicy(
        PermissionMode.DEFAULT, [Rule(tool="bash", pattern=r"pytest .*", decision="allow")], cwd=tmp_path
    )
    assert policy.check("bash", {"command": "pytest -k foo"}) == "allow"
    assert policy.check("bash", {"command": "rm -rf build"}) == "ask"


def test_an_invalid_bash_pattern_does_not_match(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [Rule(tool="bash", pattern="[", decision="allow")], cwd=tmp_path)
    assert policy.check("bash", {"command": "anything"}) == "ask"


def test_paths_outside_the_working_directory_are_denied(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [], cwd=tmp_path)
    assert policy.check("write", {"path": "../escape.py"}) == "deny"
    assert policy.check("read", {"path": "/etc/passwd"}) == "deny"


def test_an_include_directory_makes_an_outside_path_allowed(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [], cwd=tmp_path, include_dirs=[str(tmp_path / "vendor")])
    assert policy.check("read", {"path": str(tmp_path / "vendor" / "lib.py")}) == "allow"


def test_evaluate_reports_the_rule_that_was_hit(tmp_path):
    policy = PermissionPolicy(
        PermissionMode.DEFAULT,
        [Rule(tool="bash", pattern="rm -rf", decision="deny", reason="dangerous")],
        cwd=tmp_path,
    )
    decision = policy.evaluate("bash", {"command": "rm -rf build"})
    assert decision.decision == "deny"
    assert decision.rule.reason == "dangerous"


def test_glob_to_regex_does_not_let_a_single_star_cross_a_slash():
    assert glob_to_regex("*.py").match("a.py")
    assert not glob_to_regex("*.py").match("dir/a.py")
    assert glob_to_regex("**/*.py").match("dir/a.py")
    assert glob_to_regex("**/*.py").match("a.py")


def test_the_bookkeeping_tools_never_need_approval(tmp_path):
    policy = PermissionPolicy(PermissionMode.DEFAULT, [], cwd=tmp_path)
    assert policy.check("todo_write", {"todos": []}) == "allow"
    assert policy.check("bash_output", {"task_id": "x"}) == "allow"
