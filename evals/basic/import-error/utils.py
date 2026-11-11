"""Helpers for the demo application."""


def slugify(text: str) -> str:
    """The text as a slug."""
    return "-".join(text.lower().split())
