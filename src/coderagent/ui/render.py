"""Rendering of a finished turn."""

import json
from typing import Any

from coderagent.core.loop import TurnResult


def render(result: TurnResult, output_format: str = "text") -> str:
    if output_format == "json":
        return render_json(result)
    if output_format == "text":
        return render_text(result)
    msg = f"Unknown output format: {output_format}"
    raise ValueError(msg)


def render_json(result: TurnResult) -> str:
    return json.dumps(
        {
            "session_id": result.session_id,
            "messages": result.messages,
            "cost": result.cost,
            "stop_reason": result.stop_reason,
        },
        ensure_ascii=False,
    )


def render_text(result: TurnResult) -> str:
    lines = []
    for message in result.messages:
        lines.extend(_render_message(message))
    lines.append(f"[stop_reason={result.stop_reason} cost={result.cost:.4f} session={result.session_id}]")
    return "\n".join(lines)


def _render_message(message: dict[str, Any]) -> list[str]:
    role = message.get("role", "")
    content = message.get("content") or ""
    if role == "tool":
        return [f"[tool] {content.strip()}"]
    if not content:
        return []
    return [content] if role == "assistant" else [f"[{role}] {content}"]
