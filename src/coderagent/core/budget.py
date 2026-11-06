"""The token budget: how much of the context window is left for the conversation."""

from dataclasses import dataclass

MODEL_CONTEXT_WINDOWS = {
    "gpt-": 128000,
    "claude": 200000,
    "deepseek": 64000,
    "qwen": 32768,
    "llama": 8192,
    "gemini": 1000000,
    "mistral": 32768,
}
"""Context windows of the model families we know. Matched as a prefix of the
model name or of the part after the provider."""


def context_window_for(model_name: str, default: int = 200000) -> int:
    """The context window of a model, looked up by name."""
    name = model_name.split("/")[-1].lower()
    for prefix, window in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(prefix):
            return window
    return default


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
