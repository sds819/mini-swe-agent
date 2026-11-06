"""The `/compact` command: shrink the conversation now, not when the budget says so."""

from coderagent.core.context import ContextEngine


def compact(context: ContextEngine) -> bool:
    """Replace the older part of the conversation with a summary.

    Returns whether anything was compacted. The compaction event is published by
    the context engine, so the UI only has to listen for it.
    """
    return context.compact()
