import pytest

from coderagent.tools.permissions import Rule
from coderagent.tools.rules import RuleError, add_rule, load_rules, load_rules_file


def _write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_rule_file_is_parsed(tmp_path):
    path = tmp_path / "rules.yaml"
    _write(
        path,
        "rules:\n"
        "  - tool: bash\n"
        "    pattern: 'git (status|diff)\\b.*'\n"
        "    decision: allow\n"
        "    reason: read-only git\n"
        "  - tool: write\n"
        '    pattern: "**/secrets/**"\n'
        "    decision: deny\n",
    )
    assert load_rules_file(path) == [
        Rule(tool="bash", pattern=r"git (status|diff)\b.*", decision="allow", reason="read-only git"),
        Rule(tool="write", pattern="**/secrets/**", decision="deny", reason=""),
    ]


def test_an_invalid_decision_is_reported_with_the_line_number(tmp_path):
    path = tmp_path / "rules.yaml"
    _write(path, "rules:\n  - tool: bash\n    pattern: ls\n    decision: maybe\n")
    with pytest.raises(RuleError, match=r":4: invalid decision 'maybe'"):
        load_rules_file(path)


def test_an_unknown_key_is_reported(tmp_path):
    path = tmp_path / "rules.yaml"
    _write(path, "rules:\n  - tool: bash\n    pattern: ls\n    decision: allow\n    typo: x\n")
    with pytest.raises(RuleError, match="unknown rule keys: typo"):
        load_rules_file(path)


def test_broken_yaml_is_reported(tmp_path):
    path = tmp_path / "rules.yaml"
    _write(path, "rules:\n  - tool: bash\n   pattern: ls\n")
    with pytest.raises(RuleError, match="invalid YAML"):
        load_rules_file(path)


def test_a_rule_file_must_be_a_mapping(tmp_path):
    path = tmp_path / "rules.yaml"
    _write(path, "- just\n- a\n- list\n")
    with pytest.raises(RuleError, match="must be a mapping"):
        load_rules_file(path)


def test_the_project_and_user_rules_are_merged_in_that_order(tmp_path):
    _write(tmp_path / ".coderagent" / "rules.yaml", "rules:\n  - tool: bash\n    pattern: ls\n    decision: allow\n")
    home = tmp_path / "home"
    _write(home / "rules.yaml", "rules:\n  - tool: bash\n    pattern: ls\n    decision: deny\n")
    rules = load_rules(tmp_path, home)
    assert [(rule.tool, rule.decision) for rule in rules] == [("bash", "allow"), ("bash", "deny")]


def test_a_missing_rule_file_is_not_an_error(tmp_path):
    assert load_rules(tmp_path, tmp_path / "home") == []


def test_add_rule_appends_to_the_user_file_and_can_be_read_back(tmp_path):
    home = tmp_path / "home"
    add_rule("bash", "pytest .*", "allow", "tests are safe", home)
    add_rule("write", "**/tmp/**", "deny", "", home)
    rules = load_rules_file(home / "rules.yaml")
    assert [(rule.tool, rule.pattern, rule.decision, rule.reason) for rule in rules] == [
        ("bash", "pytest .*", "allow", "tests are safe"),
        ("write", "**/tmp/**", "deny", ""),
    ]


def test_add_rule_keeps_the_rules_that_are_already_there(tmp_path):
    home = tmp_path / "home"
    add_rule("bash", "ls", "allow", "", home)
    add_rule("bash", "pwd", "allow", "", home)
    assert len(load_rules_file(home / "rules.yaml")) == 2
