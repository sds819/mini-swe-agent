"""Token estimation.

`tiktoken` gives an exact count but downloads its vocabulary on first use, so every
call is guarded: when it is unavailable or offline the heuristic takes over. The
estimate only drives decisions (compact or not), the API has the last word.
"""

import json
from functools import lru_cache

CHARS_PER_TOKEN = 3.6
MESSAGE_OVERHEAD = 4

try:  # pragma: no cover - depends on the environment
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


@lru_cache(maxsize=1)
def _encoding():
    if tiktoken is None:
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def message_text(message: dict) -> str:
    """The part of a message that costs tokens."""
    parts = [str(message.get("content") or "")]
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        parts.append(str(function.get("name") or ""))
        parts.append(str(function.get("arguments") or ""))
    return "\n".join(part for part in parts if part)


def estimate_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    """Rough token count of a conversation, including the tool schemas."""
    encoding = _encoding()
    if encoding is not None:
        total = sum(MESSAGE_OVERHEAD + len(encoding.encode(message_text(message))) for message in messages)
        if tools:
            total += len(encoding.encode(json.dumps(tools, ensure_ascii=False)))
        return total
    characters = sum(len(message_text(message)) for message in messages)
    if tools:
        characters += len(json.dumps(tools, ensure_ascii=False))
    return int(characters / CHARS_PER_TOKEN) + MESSAGE_OVERHEAD * len(messages)


def count_text_tokens(text: str) -> int:
    encoding = _encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return int(len(text) / CHARS_PER_TOKEN)


def _cheap_tokens(text: str) -> float:
    """Token estimate without touching the tokenizer, for splitting decisions."""
    return len(text) / CHARS_PER_TOKEN


def trim_text(text: str, max_tokens: int) -> tuple[str, dict]:
    """Keep the head and the tail of long text, elide the middle."""
    if count_text_tokens(text) <= max_tokens:
        return text, {}
    head = int(max_tokens * 0.4 * CHARS_PER_TOKEN)
    tail = int(max_tokens * 0.4 * CHARS_PER_TOKEN)
    head_text, tail_text = text[:head], text[-tail:] if tail else ""
    elided_characters = max(0, len(text) - len(head_text) - len(tail_text))
    elided_lines = max(0, text.count("\n") - head_text.count("\n") - tail_text.count("\n"))
    elided_tokens = max(0, count_text_tokens(text) - count_text_tokens(head_text) - count_text_tokens(tail_text))
    marker = f"\n... [{elided_lines} lines, {elided_tokens} tokens elided, use grep/offset to view that region] ...\n"
    trimmed = f"{head_text}{marker}{tail_text}" if tail else f"{head_text}{marker}"
    return trimmed, {
        "elided_characters": elided_characters,
        "elided_lines": elided_lines,
        "elided_tokens": elided_tokens,
    }


def trim_lines(lines: list[str], max_tokens: int) -> tuple[list[str], dict]:
    """Keep the head and the tail of a list of lines, elide the middle.

    The marker in the middle is not a line of the file, so the caller needs to know
    how many lines came from the head to keep the line numbers right.
    """
    if count_text_tokens("\n".join(lines)) <= max_tokens:
        return lines, {}
    budget = max(1.0, max_tokens * 0.4)
    head_end = 0
    used = 0.0
    while head_end < len(lines):
        cost = _cheap_tokens(lines[head_end]) + 1
        if used + cost > budget and head_end > 0:
            break
        used += cost
        head_end += 1
    tail_start = len(lines)
    used = 0.0
    while tail_start > head_end:
        cost = _cheap_tokens(lines[tail_start - 1]) + 1
        if used + cost > budget and tail_start < len(lines):
            break
        used += cost
        tail_start -= 1
    elided = tail_start - head_end
    marker = [f"... [{elided} lines elided, use offset to view that region] ..."]
    trimmed = lines[:head_end] + marker + lines[tail_start:]
    return trimmed, {
        "elided_lines": elided,
        "start_line": head_end + 1,
        "end_line": tail_start,
        "head_lines": head_end,
    }
