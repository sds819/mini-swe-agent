"""The `/rewind` command: put the files back the way they were before a change."""

from pathlib import Path

from coderagent.core.checkpoint import Checkpoint, CheckpointStore, restore_files
from coderagent.core.context import ContextEngine


def list_checkpoints(store: CheckpointStore, session_id: str) -> list[Checkpoint]:
    """The checkpoints of a session, oldest first."""
    return store.all(session_id)


def rewind(context: ContextEngine, checkpoints: CheckpointStore, checkpoint_id: str, cwd: Path) -> list[str]:
    """Restore the files of a checkpoint and roll the conversation back to it.

    Returns the paths that were changed. The conversation is not deleted but marked
    as reverted, so the event log stays the source of truth.
    """
    checkpoint = checkpoints.get(context.session.id, checkpoint_id)
    if checkpoint is None:
        raise ValueError(f"no checkpoint '{checkpoint_id}' in this session")
    changed = restore_files(checkpoint, cwd)
    context.rewind_to(checkpoint.messages)
    return changed
