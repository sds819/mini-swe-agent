"""The context window follows the model, unless the configuration sets it."""

from coderagent.config.schema import Config, ContextConfig
from coderagent.core.budget import BudgetGuard, context_window_for
from coderagent.run import _context_config


def test_the_window_is_looked_up_by_the_model_name():
    assert context_window_for("deepseek/deepseek-flash") == 64000
    assert context_window_for("anthropic/claude-sonnet-4-5") == 200000
    assert context_window_for("openai/gpt-4o") == 128000
    assert context_window_for("moonshot/kimi-k2.5") == 262144
    assert context_window_for("minimax/minimax-m2") == 204800


def test_an_unknown_model_gets_the_default_window():
    assert context_window_for("some/unknown-model") == 200000
    assert context_window_for("") == 200000


def test_the_configuration_wins_over_the_lookup():
    config = Config(context=ContextConfig(context_window=12345))
    assert _context_config(config, "deepseek/deepseek-flash").context_window == 12345


def test_the_model_decides_when_the_configuration_is_silent():
    config = Config(context=ContextConfig())
    assert _context_config(config, "deepseek/deepseek-flash").context_window == 64000


def test_the_guard_reserves_the_output_tokens():
    guard = BudgetGuard(context_window=100000, reserved_output=8000)
    assert guard.limit() == 92000
    assert guard.should_compact(95000) is True
    assert guard.should_compact(50000) is False
