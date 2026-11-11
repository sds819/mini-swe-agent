"""Model routing: which model answers which purpose.

The routing has four dimensions:

- `purpose`: a fixed mapping of purpose to model (`main`, `cheap`, `summarize`, `reflect`).
- `complexity`: a big job gets a stronger model.
- `budget`: when the money is nearly gone, a cheaper model takes over.
- `user_override`: the model the user picked with `/model` wins over everything.

The rules are small expressions on the state of the session, like `tokens > 50000`.
They are parsed, not evaluated, so a configuration file cannot run code.
"""

from dataclasses import dataclass

from coderagent.config.schema import ModelConfig
from coderagent.models.backends import LiteLLMBackend

COMPARISONS = {
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
}

STRONG_PURPOSE = "strong"
"""The purpose of a model that is stronger than the main one."""
CHEAP_PURPOSE = "cheap"
"""The purpose of a model that is cheaper than the main one."""

STRONG_TOKENS = 50000
STRONG_TURNS = 30
BUDGET_SHARE = 0.8
"""The share of the budget at which the agent moves to a cheaper model."""


@dataclass
class RoutingRule:
    """A condition on the state of the session and the purpose it leads to."""

    when: str
    purpose: str

    def matches(self, context: dict) -> bool:
        """True when the condition holds for this context. Only numbers are compared."""
        parts = self.when.split()
        if len(parts) != 3:
            return False
        key, operator, value = parts
        if key not in context or operator not in COMPARISONS:
            return False
        try:
            right = float(value)
        except ValueError:
            return False
        left = context[key]
        if isinstance(left, bool) or not isinstance(left, (int, float)):
            return False
        try:
            return COMPARISONS[operator](left, right)
        except TypeError:
            return False


class ModelRouter:
    """Picks the model of a turn."""

    def __init__(self, config: ModelConfig, gateway=None) -> None:
        self.config = config
        self.gateway = gateway
        self.override = ""
        """The model the user picked. It wins over every rule."""
        self.main_model = config.model_name
        """The model of the main loop. The one the agent falls back to."""

    def resolve(self, purpose: str, context: dict | None = None) -> str:
        """The name of the model to use for this purpose. Empty means: keep the current one."""
        context = context or {}
        if self.override:
            return self.override
        target = self._purpose(purpose, context)
        name = self.config.routing.get(target, "")
        if not name and target == "main":
            return self.main_model
        return name

    def explain(self, context: dict) -> str:
        """Why the main loop would use another model."""
        if context.get("budget") and float(context.get("cost") or 0.0) >= context["budget"] * BUDGET_SHARE:
            return "the budget is nearly used up"
        if _token_budget_tight(context):
            return "the token budget is nearly used up"
        if float(context.get("tokens") or 0) > STRONG_TOKENS:
            return "the context has grown"
        if int(context.get("turns") or 0) > STRONG_TURNS:
            return "the session has many turns"
        for rule in self.config.routing_rules:
            if RoutingRule(rule.when, rule.purpose).matches(context):
                return f"the rule '{rule.when}' holds"
        return "the rules of the routing say so"

    def backend_for(self, name: str):
        """The backend of a model name."""
        return LiteLLMBackend(
            name,
            model_kwargs=self.config.model_kwargs,
            litellm_config=self.config.litellm_config,
        )

    def _purpose(self, purpose: str, context: dict) -> str:
        """The purpose tier this call belongs to."""
        for rule in self.config.routing_rules:
            if RoutingRule(rule.when, rule.purpose).matches(context):
                return rule.purpose
        if purpose != "main":
            return purpose
        return self._default_purpose(context)

    def _default_purpose(self, context: dict) -> str:
        """The policy of the main loop: cheaper when the budget is tight, stronger when it is big."""
        budget = float(context.get("budget") or 0.0)
        if budget and float(context.get("cost") or 0.0) >= budget * BUDGET_SHARE:
            return CHEAP_PURPOSE
        if _token_budget_tight(context):
            """A model without a price spends no money, so the token budget is the budget."""
            return CHEAP_PURPOSE
        if float(context.get("tokens") or 0) > STRONG_TOKENS:
            return STRONG_PURPOSE
        if int(context.get("turns") or 0) > STRONG_TURNS:
            return STRONG_PURPOSE
        return "main"


def _token_budget_tight(context: dict) -> bool:
    """True when the tokens of the session are close to the token budget."""
    budget = float(context.get("token_budget") or 0.0)
    return bool(budget) and float(context.get("tokens_used") or 0.0) >= budget * BUDGET_SHARE


__all__ = ["CHEAP_PURPOSE", "RoutingRule", "STRONG_PURPOSE", "ModelRouter"]
