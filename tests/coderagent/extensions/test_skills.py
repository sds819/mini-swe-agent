"""The skills: the packages of instructions the model may load."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.events import EventBus
from coderagent.core.session import SessionStore
from coderagent.extensions.skills import load_skills, parse_skill, skill_index
from coderagent.run import build_loop
from coderagent.testing.factory import build_context
from coderagent.testing.scripted_model import ScriptedModel

SKILL = """---
name: pdf-report
description: Make a PDF report out of a folder of notes.
---

Use `scripts/make_report.py` to build the report.
"""


def _write(directory: Path, name: str = "pdf-report", text: str = SKILL) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_skill_is_parsed(tmp_path):
    path = _write(Path(tmp_path) / ".coderagent" / "skills")
    skill = parse_skill(path)
    assert skill is not None
    assert skill.name == "pdf-report"
    assert skill.description == "Make a PDF report out of a folder of notes."
    assert "make_report.py" in skill.body


def test_a_skill_without_front_matter_is_not_used(tmp_path):
    path = _write(Path(tmp_path) / ".coderagent" / "skills", text="Just a note.")
    assert parse_skill(path) is None


def test_the_project_skill_is_found(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "skills")
    assert set(load_skills(tmp_path)) == {"pdf-report"}


def test_the_project_skill_wins_over_the_user_one(tmp_path):
    home = Path(tmp_path) / "home"
    _write(home / ".coderagent" / "skills", text=SKILL.replace("PDF report", "user one"))
    _write(Path(tmp_path) / ".coderagent" / "skills", text=SKILL.replace("PDF report", "project one"))
    skills = load_skills(tmp_path, home)
    assert skills["pdf-report"].description == "Make a project one out of a folder of notes."


def test_the_index_names_every_skill(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "skills")
    index = skill_index(load_skills(tmp_path))
    assert "pdf-report" in index
    assert "Make a PDF report" in index


def test_the_index_is_empty_without_skills(tmp_path):
    assert skill_index(load_skills(tmp_path)) == ""


def _loop(tmp_path, config: Config | None = None):
    return build_loop(
        config or Config(),
        tmp_path,
        model=ScriptedModel([{"role": "assistant", "content": "ok"}]),
        store=SessionStore(Path(tmp_path) / "sessions"),
        bus=EventBus(),
    )


def test_the_skill_tool_is_part_of_the_agent(tmp_path):
    loop = _loop(tmp_path)
    assert "skill" in loop.executor.registry.names()


def test_the_skill_tool_can_be_switched_off(tmp_path):
    config = Config()
    config.tools.disabled = ["skill"]
    assert "skill" not in _loop(tmp_path, config).executor.registry.names()


def test_the_index_of_the_skills_goes_into_the_system_prompt(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "skills")
    loop = _loop(tmp_path)
    assert "pdf-report" in loop.context.system_prompt


def test_the_skill_tool_gives_the_instructions(tmp_path):
    _write(Path(tmp_path) / ".coderagent" / "skills")
    loop = _loop(tmp_path)
    result = loop.executor.registry.get("skill").run({"name": "pdf-report"}, build_context(tmp_path))
    assert "make_report.py" in result.content
    assert not result.is_error


def test_the_skill_tool_says_when_the_skill_is_unknown(tmp_path):
    loop = _loop(tmp_path)
    result = loop.executor.registry.get("skill").run({"name": "nope"}, build_context(tmp_path))
    assert result.is_error
    assert "nope" in result.content
