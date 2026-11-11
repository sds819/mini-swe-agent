"""Checkpoints: the file contents as they were before the agent changed them.

A checkpoint is taken before every write. Rewinding restores the old contents.
Only files are rolled back: what a command did to the outside world stays done.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from coderagent.core.redact import has_secret, redact
from coderagent.paths import config_home


@dataclass
class Checkpoint:
    id: str
    timestamp: float
    turn: int
    kind: str
    """`file_diff` for the file contents, `container_commit` for a container image."""
    payload: dict = field(default_factory=dict)
    """For `file_diff`: `{path: old_content}`, where `None` means the file did not exist."""
    messages: int = 0
    """How many messages the conversation had when the checkpoint was taken."""
    redacted: list[str] = field(default_factory=list)
    """The paths whose content held a secret, so it cannot be put back exactly."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "turn": self.turn,
            "kind": self.kind,
            "payload": self.payload,
            "messages": self.messages,
            "redacted": self.redacted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(
            id=data["id"],
            timestamp=data.get("timestamp", 0.0),
            turn=data.get("turn", 0),
            kind=data.get("kind", "file_diff"),
            payload=data.get("payload", {}),
            messages=data.get("messages", 0),
            redacted=data.get("redacted", []),
        )

    @property
    def paths(self) -> list[str]:
        return list(self.payload)


class CheckpointStore:
    """The checkpoints of a session, on disk."""

    def __init__(self, root: Path | None = None, keep: int = 50) -> None:
        self.root = Path(root) if root else config_home() / "checkpoints"
        self.keep = keep

    def path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def create(
        self, session_id: str, turn: int, kind: str, payload: dict, messages: int = 0, redacted: list[str] | None = None
    ) -> Checkpoint:
        checkpoint = Checkpoint(
            id=f"{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            timestamp=time.time(),
            turn=turn,
            kind=kind,
            payload=payload,
            messages=messages,
            redacted=redacted or [],
        )
        checkpoints = self.all(session_id)
        checkpoints.append(checkpoint)
        self._write(session_id, checkpoints[-self.keep :])
        return checkpoint

    def all(self, session_id: str) -> list[Checkpoint]:
        path = self.path(session_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Checkpoint.from_dict(item) for item in data]

    def get(self, session_id: str, checkpoint_id: str) -> Checkpoint | None:
        for checkpoint in self.all(session_id):
            if checkpoint.id == checkpoint_id:
                return checkpoint
        return None

    def _write(self, session_id: str, checkpoints: list[Checkpoint]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(session_id)
        path.write_text(
            json.dumps([checkpoint.to_dict() for checkpoint in checkpoints], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        path.chmod(0o600)
        """The checkpoints hold the content of the files of the project."""


def snapshot_file(path: Path) -> str | None:
    """The content of a file before it is changed. `None` when it does not exist."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def create_file_checkpoint(
    store: CheckpointStore,
    session_id: str,
    turn: int,
    cwd: Path,
    path: str,
    messages: int = 0,
) -> Checkpoint | None:
    """Snapshot a file before a write tool changes it.

    A file that holds a secret is stored without it, so it cannot be put back
    exactly. The path is remembered, so the user can be told about it.
    """
    target = Path(path)
    if not target.is_absolute():
        target = Path(cwd) / target
    try:
        name = str(target.relative_to(Path(cwd)))
    except ValueError:
        name = str(target)
    content = snapshot_file(target)
    secret = content is not None and has_secret(content)
    payload = {name: redact(content) if secret else content}
    return store.create(session_id, turn, "file_diff", payload, messages, [name] if secret else [])


def restore_files(checkpoint: Checkpoint, cwd: Path) -> list[str]:
    """Put the files back the way they were. Returns the paths that changed.

    A file whose content was redacted is left alone: writing it back would put
    a placeholder where the secret was.
    """
    changed = []
    redacted = set(getattr(checkpoint, "redacted", []))
    for name, content in checkpoint.payload.items():
        if name in redacted:
            continue
        path = Path(cwd) / name
        if content is None:
            if path.exists():
                path.unlink()
                changed.append(name)
            continue
        if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            changed.append(name)
    return changed
