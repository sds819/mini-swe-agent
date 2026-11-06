"""The conversation history, split into turns.

A turn is one user message plus everything the model did in response: its assistant
message and the tool results that followed. Cutting a history on a turn boundary is
what keeps the tool messages attached to the assistant message that asked for them.
"""

from coderagent.core.tokens import estimate_tokens


class History:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.messages: list[dict] = list(messages or [])

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self):
        return iter(self.messages)

    def append(self, message: dict) -> None:
        self.messages.append(message)

    def extend(self, messages: list[dict]) -> None:
        self.messages.extend(messages)

    def turn_starts(self) -> list[int]:
        """Indices where a new turn begins."""
        return [index for index, message in enumerate(self.messages) if message.get("role") == "user"]

    def turn_count(self) -> int:
        return len(self.turn_starts())

    def recent_turns(self, turns: int) -> list[dict]:
        """The last `turns` turns, oldest first."""
        if turns <= 0:
            return []
        starts = self.turn_starts()
        if not starts:
            return list(self.messages)
        index = starts[max(0, len(starts) - turns)]
        return list(self.messages[index:])

    def split_at(self, index: int) -> tuple[list[dict], list[dict]]:
        """Split into (older, newer). The two halves concatenate back to the original."""
        return list(self.messages[:index]), list(self.messages[index:])

    def token_count(self, tools: list[dict] | None = None) -> int:
        return estimate_tokens(self.messages, tools)

    def tail_from_turn(self, turns: int) -> int:
        """Index where the last `turns` turns start."""
        starts = self.turn_starts()
        if not starts:
            return 0
        return starts[max(0, len(starts) - turns)]
