"""Session state and its persistence. Events are the source of truth, the session is derived."""

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from coderagent.core.events import Event, EventType
from coderagent.paths import config_home


class SessionState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    ERROR = "error"


@dataclass
class Session:
    id: str
    cwd: Path
    created_at: float
    updated_at: float
    state: SessionState = SessionState.IDLE
    model_name: str = ""
    permission_mode: str = "default"
    turn_count: int = 0
    total_cost: float = 0.0
    metadata: dict = field(default_factory=dict)


def default_root() -> Path:
    """Directory holding all session files. Overridable via `MSWEA_CODER_HOME`."""
    return config_home() / "sessions"


class SessionStore:
    """Append-only JSONL event log. Replaying the log rebuilds the session."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_root()

    def create(self, cwd: Path) -> Session:
        session = Session(
            id=f"{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}",
            cwd=Path(cwd),
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_meta(session)
        self.append(
            session.id,
            Event(
                type=EventType.STATE_CHANGE,
                session_id=session.id,
                timestamp=session.created_at,
                payload={"state": session.state.value, "cwd": str(session.cwd), "created_at": session.created_at},
            ),
        )
        return session

    def path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.jsonl"

    def meta_path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.meta.json"

    def append(self, session_id: str, event: Event) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path(session_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            f.flush()

    def events(self, session_id: str) -> list[Event]:
        path = self.path(session_id)
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = Event.from_dict(json.loads(line))
            if event is not None:
                events.append(event)
        return events

    def rebuild(self, session_id: str) -> Session:
        """Replay the event log to get the current session state."""
        session = Session(id=session_id, cwd=Path("."), created_at=0.0, updated_at=0.0)
        for event in self.events(session_id):
            payload = event.payload
            if event.type == EventType.STATE_CHANGE:
                session.state = SessionState(payload.get("state", session.state.value))
                if "cwd" in payload:
                    session.cwd = Path(payload["cwd"])
                if "created_at" in payload:
                    session.created_at = payload["created_at"]
                if "model_name" in payload:
                    session.model_name = payload["model_name"]
                if "permission_mode" in payload:
                    session.permission_mode = payload["permission_mode"]
            elif event.type == EventType.USER_MESSAGE:
                session.turn_count += 1
            elif event.type == EventType.ASSISTANT_MESSAGE:
                session.total_cost += payload.get("cost", 0.0)
            elif event.type == EventType.TOOL_RESULT and payload.get("todos"):
                session.metadata["todos"] = payload["todos"]
            session.updated_at = event.timestamp
        return session

    def list(self, cwd: Path | None = None) -> list[Session]:
        """All sessions, newest first. Optionally restricted to a working directory."""
        if not self.root.exists():
            return []
        sessions = []
        for meta_path in self.root.glob("*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if cwd is not None and Path(meta.get("cwd", "")) != Path(cwd):
                continue
            sessions.append(self.rebuild(meta["id"]))
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def _write_meta(self, session: Session) -> None:
        meta = {
            "id": session.id,
            "cwd": str(session.cwd),
            "created_at": session.created_at,
            "model_name": session.model_name,
        }
        self.meta_path(session.id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
