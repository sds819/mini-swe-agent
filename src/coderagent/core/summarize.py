"""Structured summaries of the part of a conversation that no longer fits in the window.

The summary is a fixed set of fields rather than free text: a model that has to
remember "what is still open" in a JSON structure keeps it better than in prose.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from coderagent.core.tokens import estimate_tokens

FIELDS = ("goal", "findings", "decisions", "files_touched", "open_questions", "next_steps", "errors_seen")
CONSERVATIVE_MESSAGES = 5

SCHEMA = """{
  "goal": "one sentence: what the user is trying to achieve",
  "findings": ["facts you confirmed, each with file:line when it comes from the code"],
  "decisions": ["technical decisions that were made and why"],
  "files_touched": [{"path": "src/cache.py", "change": "what changed", "state": "modified"}],
  "open_questions": ["questions that are still unanswered"],
  "next_steps": ["the concrete next steps"],
  "errors_seen": ["errors that were hit and how they were resolved"]
}"""

PROMPT = """You are summarizing a coding session so that it can continue after the original messages are dropped.

Answer with a single JSON object and nothing else. Use exactly these keys, and use [] for a key you have nothing for:
{schema}

The conversation to summarize:
"""

MERGE_PROMPT = """You are merging the partial summaries of a coding session into one summary.

Answer with a single JSON object and nothing else. Use exactly these keys, and use [] for a key you have nothing for:
{schema}

Keep every fact that is still true. The partial summaries are in the order of the
conversation, so the later ones describe the newer state of the work.

The partial summaries:
"""


@dataclass
class Summary:
    goal: str = ""
    findings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    files_touched: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    errors_seen: list[str] = field(default_factory=list)
    recent_errors: list[str] = field(default_factory=list)
    """Tool errors from the compacted part. Derived from the messages, not from the model."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Summary":
        def entries(key: str) -> list:
            value = data.get(key)
            return list(value) if isinstance(value, list) else []

        goal = data.get("goal")
        return cls(
            goal=goal if isinstance(goal, str) else "",
            findings=[str(item) for item in entries("findings")],
            decisions=[str(item) for item in entries("decisions")],
            files_touched=[item for item in entries("files_touched") if isinstance(item, dict)],
            open_questions=[str(item) for item in entries("open_questions")],
            next_steps=[str(item) for item in entries("next_steps")],
            errors_seen=[str(item) for item in entries("errors_seen")],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "findings": self.findings,
            "decisions": self.decisions,
            "files_touched": self.files_touched,
            "open_questions": self.open_questions,
            "next_steps": self.next_steps,
            "errors_seen": self.errors_seen,
        }

    def render(self) -> str:
        lines = [
            "<session_summary>",
            "The earlier part of this conversation was compacted. Keep these facts and continue the work.",
            "",
            f"goal: {self.goal}",
            "findings:",
            *[f"- {item}" for item in self.findings],
            "decisions:",
            *[f"- {item}" for item in self.decisions],
            "files_touched:",
            *[
                f"- {item.get('path', '?')} ({item.get('state', 'modified')}): {item.get('change', '')}"
                for item in self.files_touched
            ],
            "open_questions:",
            *[f"- {item}" for item in self.open_questions],
            "next_steps:",
            *[f"- {item}" for item in self.next_steps],
            "errors_seen:",
            *[f"- {item}" for item in self.errors_seen],
        ]
        if self.recent_errors:
            lines += ["recent_errors:", *[f"- {item}" for item in self.recent_errors]]
        lines.append("</session_summary>")
        return "\n".join(lines)


def parse_summary(text: str) -> Summary | None:
    """Parse the model's answer. Returns None when it is not usable."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return Summary.from_dict(data)


def summarize_prompt(messages: list[dict]) -> str:
    """The prompt that asks the model for the summary."""
    transcript = []
    for message in messages:
        role = message.get("role", "?")
        content = str(message.get("content") or "")
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            content += f"\n[tool call {function.get('name', '?')}: {function.get('arguments', '')}]"
        transcript.append(f"{role}: {content}")
    return PROMPT.format(schema=SCHEMA) + "\n\n".join(transcript)


def merge_prompt(summaries: list["Summary"], previous: str = "") -> str:
    """The prompt that asks the model to merge the partial summaries into one."""
    parts = [summary.to_dict() for summary in summaries]
    text = MERGE_PROMPT.format(schema=SCHEMA)
    if previous:
        text += f"\nThe summary of the part that was compacted before:\n{previous}\n"
    return text + json.dumps(parts, ensure_ascii=False, indent=2)


def chunk_messages(messages: list[dict], max_tokens: int) -> list[list[dict]]:
    """Split the messages into chunks that each fit into one summarizer prompt.

    A turn is never split in two, so a tool result keeps the assistant message
    that asked for it. A turn that is bigger than the limit on its own is split
    at message boundaries, because there is nothing else to do.
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for turn in _turns(messages):
        for part in _split_oversized(turn, max_tokens):
            size = estimate_tokens(part)
            if current and used + size > max_tokens:
                chunks.append(current)
                current = []
                used = 0
            current.extend(part)
            used += size
    if current:
        chunks.append(current)
    return chunks


def merge_summaries(summaries: list["Summary"]) -> "Summary":
    """Merge the summaries of the parts into one, without losing anything.

    The fallback of the merging: no model, no loss, but the result grows with
    the number of the parts.
    """
    goal = ""
    findings: list[str] = []
    decisions: list[str] = []
    open_questions: list[str] = []
    next_steps: list[str] = []
    errors_seen: list[str] = []
    files: dict[str, dict] = {}
    for summary in summaries:
        if summary.goal:
            goal = summary.goal
        findings += summary.findings
        decisions += summary.decisions
        open_questions += summary.open_questions
        next_steps += summary.next_steps
        errors_seen += summary.errors_seen
        for index, item in enumerate(summary.files_touched):
            files[str(item.get("path") or f"#{index}")] = item
    return Summary(
        goal=goal,
        findings=_unique(findings),
        decisions=_unique(decisions),
        files_touched=list(files.values()),
        open_questions=_unique(open_questions),
        next_steps=_unique(next_steps),
        errors_seen=_unique(errors_seen),
    )


def _turns(messages: list[dict]) -> list[list[dict]]:
    """The messages of the conversation, one list per turn."""
    turns: list[list[dict]] = []
    current: list[dict] = []
    for message in messages:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    return turns


def _split_oversized(turn: list[dict], max_tokens: int) -> list[list[dict]]:
    """Split a turn that does not fit into one prompt."""
    if estimate_tokens(turn) <= max_tokens:
        return [turn]
    parts: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for message in turn:
        size = estimate_tokens([message])
        if current and used + size > max_tokens:
            parts.append(current)
            current = []
            used = 0
        current.append(message)
        used += size
    if current:
        parts.append(current)
    return parts


def _unique(items: list[str]) -> list[str]:
    """The items without the duplicates, in the order they came in."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def conservative_summary(messages: list[dict]) -> Summary:
    """Fallback when the model does not return a usable summary."""
    findings = []
    for message in messages[-CONSERVATIVE_MESSAGES:]:
        content = str(message.get("content") or "").strip()
        if content:
            findings.append(f"{message.get('role', '?')}: {content[:400]}")
    return Summary(
        goal="the earlier part of the conversation was compacted",
        findings=findings,
        next_steps=["re-read the files that were mentioned to recover the details"],
    )


def recent_errors(messages: list[dict], limit: int = 3) -> list[str]:
    """The last few tool errors, so they do not get lost in the compaction."""
    errors = []
    for message in messages:
        content = str(message.get("content") or "")
        if message.get("role") == "tool" and content.startswith("Error:"):
            errors.append(content[:300])
    return errors[-limit:]
