"""What a shell command is, and where it may reach.

The known commands are a tree of prefixes: `git` has subcommands and they do
not all do the same. A command that only looks around is safe, one that
destroys something or sends it out is dangerous, and the rest is unknown.

The disk is bounded like the file tools are: the working directory is where the
agent works, and the system directories hold the programs it runs.
"""

import re
import shlex
from pathlib import Path

SYSTEM_PREFIXES = ("/bin", "/sbin", "/usr", "/lib", "/lib64", "/opt")
"""Where the programs of the system live. A command may name them."""

COMMANDS: dict[str, object] = {
    # the commands that only look around
    "ls": None,
    "pwd": None,
    "echo": None,
    "cat": None,
    "head": None,
    "tail": None,
    "wc": None,
    "stat": None,
    "file": None,
    "du": None,
    "df": None,
    "tree": None,
    "which": None,
    "basename": None,
    "dirname": None,
    "realpath": None,
    "date": None,
    "whoami": None,
    "id": None,
    "uname": None,
    "hostname": None,
    "diff": None,
    "cmp": None,
    "grep": None,
    "rg": None,
    "jq": None,
    "md5sum": None,
    "shasum": None,
    "git": {
        "status": None,
        "diff": None,
        "log": None,
        "show": None,
        "blame": None,
        "rev-parse": None,
        "ls-files": None,
        "shortlog": None,
        "cat-file": None,
        "describe": None,
        "push": "sends commits to a remote",
        "pull": "changes the working tree from a remote",
        "fetch": "downloads from a remote",
        "clone": "downloads a repository",
        "reset": "throws the commits away",
        "clean": "deletes the files that are not tracked",
        "checkout": "changes the working tree",
        "commit": "writes to the history of the repository",
        "add": "writes to the index of the repository",
        "branch": "changes the branches of the repository",
        "rebase": "rewrites the history of the repository",
        "merge": "merges into the working tree",
        "tag": "changes the tags of the repository",
        "stash": "hides the changes of the working tree",
        "config": "changes the settings of the repository",
        "remote": "changes the remotes of the repository",
        "submodule": "changes the submodules of the repository",
    },
    # the commands that destroy something or send it out
    "rm": "deletes files",
    "rmdir": "deletes directories",
    "mv": "moves files",
    "cp": "copies files",
    "chmod": "changes the permissions of files",
    "chown": "changes the owner of files",
    "dd": "writes blocks to a device",
    "mkfs": "makes a filesystem",
    "curl": "sends data out of the machine",
    "wget": "downloads from the network",
    "ssh": "opens a connection to another machine",
    "scp": "copies files from another machine",
    "sftp": "opens a connection to another machine",
    "rsync": "copies files to another machine",
    "nc": "opens a network connection",
    "kill": "stops a process",
    "killall": "stops the processes of a name",
    "pkill": "stops the processes of a pattern",
    "sudo": "runs a command as another user",
    "su": "runs a shell as another user",
    "docker": "controls the containers",
    "kubectl": "controls the clusters of kubernetes",
    "terraform": "changes the infrastructure",
    "aws": "calls amazon web services",
    "gcloud": "calls google cloud",
    "az": "calls microsoft azure",
    "npm": "installs and runs javascript packages",
    "npx": "runs a javascript package",
    "yarn": "installs and runs javascript packages",
    "pnpm": "installs and runs javascript packages",
    "pip": "installs python packages",
    "pip3": "installs python packages",
    "apt": "installs the packages of the system",
    "apt-get": "installs the packages of the system",
    "yum": "installs the packages of the system",
    "dnf": "installs the packages of the system",
    "brew": "installs the packages of the system",
    "crontab": "changes the jobs of the scheduler",
    "systemctl": "controls the services of the system",
    "launchctl": "controls the services of the system",
}
"""The tree of the known commands. A leaf is `None` when it is safe, a text when it is dangerous."""

_MISSING = object()
"""The marker for a command that is not in the tree."""

EMBEDDED_PATH = re.compile(r"""['"(]\s*(/[^\s'"()]+)""")
"""An absolute path inside a quoted word, like the file of a small script."""


def segments(command: str) -> list[str]:
    """The parts of a command: what a shell would run one after the other."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            current.append(char)
        elif command[index : index + 2] in ("&&", "||"):
            parts.append("".join(current))
            current = []
            index += 1
        elif char in ";|\n":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def tokens(segment: str) -> list[str]:
    """The words of a part, with the quotes still on them."""
    lexer = shlex.shlex(segment, posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return segment.split()


def classify_segment(segment: str) -> tuple[str, str]:
    """The kind of a part: `safe`, `dangerous` or `unknown`, and why it is dangerous."""
    parts = tokens(segment)
    if not parts:
        return "unknown", ""
    program = parts[0].strip("\"'")
    if "/" in program:
        """A program of a path is not one of the known ones."""
        return "unknown", ""
    if writes(segment):
        """A command that redirects writes something, whatever it is."""
        return "unknown", ""
    value = COMMANDS.get(program, _MISSING)
    if isinstance(value, dict):
        subcommand = _subcommand(parts[1:])
        value = value.get(subcommand, _MISSING) if subcommand else _MISSING
    if value is _MISSING:
        return "unknown", ""
    if value is None:
        return "safe", ""
    return "dangerous", str(value)


def classify(command: str) -> tuple[str, str]:
    """The kind of a command: the strictest of its parts."""
    kinds = [classify_segment(segment) for segment in segments(command)]
    if not kinds:
        return "unknown", ""
    if any(kind == "dangerous" for kind, _ in kinds):
        return "dangerous", next(reason for kind, reason in kinds if kind == "dangerous")
    if all(kind == "safe" for kind, _ in kinds):
        return "safe", ""
    return "unknown", ""


def writes(segment: str) -> bool:
    """Whether a part writes a file with a redirection."""
    parts = tokens(segment)
    for index, token in enumerate(parts):
        value = token.strip("\"'")
        if value in (">", ">>"):
            target = parts[index + 1].strip("\"'") if index + 1 < len(parts) else ""
        elif ">" in value:
            target = value.split(">", 1)[1]
        else:
            continue
        if target and not target.startswith("/dev/null"):
            return True
    return False


def outside_paths(command: str, cwd: Path, include_dirs: list[Path]) -> list[str]:
    """The paths a command reaches that are outside the working directory.

    The system directories are open for the programs, the working directory for
    everything else. A command that changes the directory moves the ground the
    paths after it are relative to.
    """
    outside: list[str] = []
    cwd = Path(cwd).resolve()
    include_dirs = [Path(directory).resolve() for directory in include_dirs]
    virtual = cwd
    for segment in segments(command):
        parts = tokens(segment)
        if not parts:
            continue
        program = parts[0].strip("\"'")
        if "/" in program and not _allowed(_resolve(program, virtual), cwd, include_dirs, system=True):
            outside.append(program)
        for token in parts[1:]:
            for candidate in _candidates(token.strip("\"'")):
                if not _allowed(_resolve(candidate, virtual), cwd, include_dirs):
                    outside.append(candidate)
        if Path(program).name == "cd" and len(parts) > 1:
            target = parts[1].strip("\"'")
            resolved = _resolve(target, virtual)
            if not _allowed(resolved, cwd, include_dirs):
                outside.append(target)
            else:
                virtual = resolved
    return outside


def _subcommand(arguments: list[str]) -> str:
    """The first argument that is not a flag."""
    for argument in arguments:
        value = argument.strip("\"'")
        if not value.startswith("-"):
            return value
    return ""


def _candidates(value: str) -> list[str]:
    """The paths a word names: the absolute ones, the home ones and the ones that climb out."""
    if not value or value.startswith("$"):
        return []
    candidates: list[str] = []
    for part in [value, *EMBEDDED_PATH.findall(value)]:
        part = part.strip("\"'")
        if not part:
            continue
        for half in [part, *part.split("=")[1:]]:
            half = half.strip("\"'")
            if half.startswith("/") or half.startswith("~"):
                candidates.append(half)
            elif ".." in half.split("/"):
                candidates.append(half)
    return candidates


def _resolve(path: str, base: Path) -> Path:
    """Where a path is, relative to the directory the command is in."""
    if path.startswith("~"):
        return Path(path).expanduser().resolve()
    if path.startswith("/"):
        return Path(path).resolve()
    return (base / path).resolve()


def _allowed(path: Path, cwd: Path, include_dirs: list[Path], system: bool = False) -> bool:
    """Whether a path is one the agent may touch."""
    if path.is_relative_to(cwd):
        return True
    if any(path.is_relative_to(directory) for directory in include_dirs):
        return True
    if system:
        return any(str(path).startswith(prefix) for prefix in SYSTEM_PREFIXES)
    return False
