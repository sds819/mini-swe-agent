"""Instruction files: the AGENTS.md / CLAUDE.md files that tell the agent how to work here.

The user level comes first, then the project level. Files in subdirectories are
loaded lazily, when a tool touches something inside them.
"""

from dataclasses import dataclass
from pathlib import Path

from coderagent.paths import config_home

PROJECT_FILES = ("AGENTS.md", "CLAUDE.md")
USER_FILE = "CLAUDE.md"


@dataclass
class InstructionBlock:
    source: str
    content: str
    path: Path

    def render(self) -> str:
        return f'<project_instructions source="{self.source}">\n{self.content.strip()}\n</project_instructions>'


def read_block(path: Path) -> InstructionBlock | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return None
    return InstructionBlock(source=path.name, content=content, path=path)


def load_instructions(cwd: Path, user_home: Path | None = None) -> list[InstructionBlock]:
    """The user level and the project level instructions, in that order."""
    blocks = []
    home = Path(user_home) if user_home else config_home()
    for path in (home / USER_FILE, Path(cwd) / "AGENTS.md", Path(cwd) / "CLAUDE.md"):
        block = read_block(path)
        if block:
            blocks.append(block)
    return blocks


def subdirectory_instructions(path: Path, cwd: Path) -> list[InstructionBlock]:
    """The instruction files of the directories between `cwd` and `path`, deepest first."""
    try:
        relative = Path(path).resolve().relative_to(Path(cwd).resolve())
    except ValueError:
        return []
    blocks = []
    directories = list(relative.parts[:-1]) if relative.name else list(relative.parts)
    for index in range(len(directories), 0, -1):
        directory = Path(cwd).joinpath(*directories[:index])
        block = read_block(directory / "AGENTS.md")
        if block:
            blocks.append(block)
    return blocks
