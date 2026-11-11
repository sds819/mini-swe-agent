"""The demo application."""

from utils import slugify_text


def title(text: str) -> str:
    """The title of a page."""
    return slugify_text(text).replace("-", " ").title()
