"""Skills: a reusable package of instructions, scripts and resources.

A skill is a directory with a `SKILL.md` in it:

    .coderagent/skills/pdf-report/
    ├── SKILL.md
    ├── scripts/
    │   └── make_report.py
    └── assets/
        └── template.docx

The front matter of `SKILL.md` says what the skill is for:

    ---
    name: pdf-report
    description: Make a PDF report out of a folder of notes.
    ---
    Use `scripts/make_report.py` to build the report...

The index of the skills goes into the system prompt. The model decides to load one
when the description fits the task, and gets the whole instruction then.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from coderagent.paths import config_home

SKILLS_DIR = "skills"
"""The directory of the skills. In the project it is under `.coderagent`."""
SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    """A skill the agent may use."""

    name: str
    description: str = ""
    body: str = ""
    """The instructions of the skill."""
    path: Path | None = None
    directory: Path | None = None

    def render(self) -> str:
        """The whole skill, as the model reads it when it loads it."""
        return f'<skill name="{self.name}">\n{self.body.strip()}\n</skill>'

    def index_line(self) -> str:
        """The one line of the index."""
        return f"- {self.name}: {self.description}" if self.description else f"- {self.name}"


def parse_skill(path: Path) -> Skill | None:
    """Read one `SKILL.md`. Returns None when the file cannot be used."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    _, _, rest = text.partition("---")
    front_matter, _, body = rest.partition("---")
    try:
        data = yaml.safe_load(front_matter) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return Skill(
        name=str(data.get("name") or path.parent.name),
        description=str(data.get("description", "")),
        body=body.strip(),
        path=path,
        directory=path.parent,
    )


def load_skills(cwd: Path, user_home: Path | None = None) -> dict[str, Skill]:
    """The skills of the project and of the user. The project wins on a name clash."""
    skills: dict[str, Skill] = {}
    for directory in _directories(cwd, user_home):
        for path in sorted(directory.glob(f"*/{SKILL_FILE}")):
            skill = parse_skill(path)
            if skill is not None:
                skills[skill.name] = skill
    return skills


def _directories(cwd: Path, user_home: Path | None) -> list[Path]:
    home = Path(user_home) if user_home else config_home()
    directories = [home / SKILLS_DIR, Path(cwd) / ".coderagent" / SKILLS_DIR]
    return [directory for directory in directories if directory.is_dir()]


def skill_index(skills: dict[str, Skill]) -> str:
    """The index of the skills, as it goes into the system prompt."""
    if not skills:
        return ""
    lines = [
        "<skills>",
        "These skills are available. Load one with the `skill` tool when its description fits the task.",
        *[skill.index_line() for skill in skills.values()],
        "</skills>",
    ]
    return "\n".join(lines)


__all__ = ["SKILL_FILE", "SKILLS_DIR", "Skill", "load_skills", "parse_skill", "skill_index"]
