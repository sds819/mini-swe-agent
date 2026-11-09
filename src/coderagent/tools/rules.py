"""Rule files: `.coderagent/rules.yaml` in the project and `~/.coderagent/rules.yaml` for the user.

Later rules win, so a user rule overrides a project rule with the same tool and pattern.
"""

from pathlib import Path
from typing import Any

import yaml

from coderagent.paths import config_home
from coderagent.tools.permissions import Rule

DECISIONS = ("allow", "ask", "deny")


class RuleError(ValueError):
    """A rule file could not be parsed."""


def _scalar(node: yaml.ScalarNode) -> Any:
    tag = node.tag
    if tag == "tag:yaml.org,2002:int":
        return int(node.value)
    if tag == "tag:yaml.org,2002:float":
        return float(node.value)
    if tag == "tag:yaml.org,2002:bool":
        return node.value.lower() in ("true", "yes", "on")
    if tag == "tag:yaml.org,2002:null":
        return None
    return node.value


def _value(node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return _scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return [_value(item) for item in node.value]
    if isinstance(node, yaml.MappingNode):
        return {key.value: _value(value) for key, value in node.value}
    return None


def _rule_from(node: yaml.Node, path: Path) -> Rule:
    if not isinstance(node, yaml.MappingNode):
        raise RuleError(f"{path}:{node.start_mark.line + 1}: each rule must be a mapping, got {type(node).__name__}")
    data: dict[str, Any] = {}
    lines: dict[str, int] = {}
    for key, value in node.value:
        data[key.value] = _value(value)
        lines[key.value] = value.start_mark.line + 1
    unknown = set(data) - {"tool", "pattern", "decision", "reason"}
    if unknown:
        name = sorted(unknown)[0]
        raise RuleError(f"{path}:{lines[name]}: unknown rule keys: {', '.join(sorted(unknown))}")
    decision = data.get("decision", "ask")
    if decision not in DECISIONS:
        line = lines.get("decision", node.start_mark.line + 1)
        raise RuleError(f"{path}:{line}: invalid decision '{decision}', expected one of {', '.join(DECISIONS)}")
    for key in ("tool", "pattern"):
        if key in data and not isinstance(data[key], str):
            raise RuleError(f"{path}:{lines[key]}: `{key}` must be a string")
    return Rule(
        tool=str(data.get("tool", "*")),
        pattern=str(data.get("pattern", "*")),
        decision=str(decision),
        reason=str(data.get("reason", "")),
    )


def load_rules_file(path: Path) -> list[Rule]:
    """Parse one rule file. Raises `RuleError` with file and line number on bad input."""
    text = path.read_text(encoding="utf-8")
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if mark else 0
        raise RuleError(f"{path}:{line}: invalid YAML: {error}") from error
    if root is None:
        return []
    if not isinstance(root, yaml.MappingNode):
        raise RuleError(f"{path}:1: the rule file must be a mapping with a `rules` key")
    for key, value in root.value:
        if key.value != "rules":
            continue
        if not isinstance(value, yaml.SequenceNode):
            raise RuleError(f"{path}:{value.start_mark.line + 1}: `rules` must be a list")
        return [_rule_from(item, path) for item in value.value]
    return []


def load_rules(project_dir: Path, user_home: Path | None = None) -> list[Rule]:
    """Project rules first, then user rules. Later entries win."""
    home = Path(user_home) if user_home else config_home()
    rules: list[Rule] = []
    for path in (Path(project_dir) / ".coderagent" / "rules.yaml", home / "rules.yaml"):
        if path.exists():
            rules.extend(load_rules_file(path))
    return rules


def _document_of(path: Path) -> dict[str, Any]:
    """The rule file as a mapping. A file that does not exist is an empty mapping."""
    if not path.exists():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RuleError(f"{path}: invalid YAML: {error}") from error
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise RuleError(f"{path}: the rule file must be a mapping with a `rules` key")
    return document


def add_rule(tool: str, pattern: str, decision: str = "allow", reason: str = "", user_home: Path | None = None) -> Path:
    """Append a rule to the user-level rule file and read it back to confirm it landed."""
    home = Path(user_home) if user_home else config_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "rules.yaml"
    document = _document_of(path)
    rules = document.get("rules") or []
    if not isinstance(rules, list):
        raise RuleError(f"{path}: `rules` must be a list")
    document["rules"] = rules + [{"tool": tool, "pattern": pattern, "decision": decision, "reason": reason}]
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    load_rules_file(path)
    return path
