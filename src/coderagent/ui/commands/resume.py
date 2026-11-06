"""The `/resume` command: pick a session again, or fork one into a new branch."""

from pathlib import Path

from coderagent.core.session import Session, SessionStore


def list_sessions(store: SessionStore, cwd: Path | None = None) -> list[Session]:
    """The sessions of this project, newest first."""
    return store.list(cwd)


def latest_session(store: SessionStore, cwd: Path | None = None) -> Session | None:
    """The session that was worked on last."""
    sessions = list_sessions(store, cwd)
    return sessions[0] if sessions else None


def resume(store: SessionStore, session_id: str) -> Session:
    """Load a session so the conversation can continue."""
    return store.rebuild(session_id)


def fork(store: SessionStore, session_id: str) -> Session:
    """Copy a session into a new one and continue there. The original stays as it was."""
    return store.fork(session_id)
