"""The token budget: how much of the context window is left for the conversation."""

from dataclasses import dataclass


@dataclass
class BudgetGuard:
    context_window: int = 200000
    reserved_output: int = 8000
    compact_threshold: float = 0.8

    def limit(self) -> int:
        """Tokens available for the context itself."""
        return max(0, self.context_window - self.reserved_output)

    def should_compact(self, estimated: int) -> bool:
        """True when the conversation is close enough to the limit to compact."""
        return estimated > min(int(self.context_window * self.compact_threshold), self.limit())
