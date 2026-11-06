"""Checkpoints: the file contents as they were before the agent changed them.

A checkpoint is taken before every write. Rewinding restores the old contents.
Only files are rolled back: what a command did to the outside world stays done.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "turn": self.turn,
            "kind": self.kind,
            "payload": self.payload,
            "messages": self.messages,
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

    def create(self, session_id: str, turn: int, kind: str, payload: dict, messages: int = 0) -> Checkpoint:
        checkpoint = Checkpoint(
            id=f"{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            timestamp=time.time(),
            turn=turn,
            kind=kind,
            payload=payload,
            messages=messages,
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
        self.path(session_id).write_text(
            json.dumps([checkpoint.to_dict() for checkpoint in checkpoints], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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
    """Snapshot a file before a write tool changes it."""
    target = Path(path)
    if not target.is_absolute():
        target = Path(cwd) / target
    try:
        name = str(target.relative_to(Path(cwd)))
    except ValueError:
        name = str(target)
    return store.create(session_id, turn, "file_diff", {name: snapshot_file(target)}, messages)


def restore_files(checkpoint: Checkpoint, cwd: Path) -> list[str]:
    """Put the files back the way they were. Returns the paths that changed."""
    changed = []
    for name, content in checkpoint.payload.items():
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
