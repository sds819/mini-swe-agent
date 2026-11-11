"""The model router: which model answers which purpose."""

from coderagent.config.schema import ModelConfig, RoutingRuleConfig
from coderagent.core.events import EventBus, EventType
from coderagent.core.loop import AgentLoop
from coderagent.core.session import SessionStore
from coderagent.models.gateway import ModelGateway
from coderagent.models.router import ModelRouter
from coderagent.testing.factory import build_executor
from coderagent.testing.scripted_model import ScriptedModel


def _config(**kwargs) -> ModelConfig:
    defaults = {
        "model_name": "main/model",
        "routing": {"cheap": "cheap/model", "strong": "strong/model", "summarize": "small/model"},
    }
    return ModelConfig(**{**defaults, **kwargs})


def test_the_main_model_is_used_when_nothing_is_routed():
    assert ModelRouter(_config()).resolve("main") == "main/model"


def test_a_purpose_is_mapped_to_its_model():
    assert ModelRouter(_config()).resolve("cheap") == "cheap/model"


def test_an_unknown_purpose_keeps_the_current_model():
    assert ModelRouter(_config()).resolve("reflect") == ""


def test_the_user_picks_the_model_and_nothing_else_matters():
    router = ModelRouter(_config())
    router.override = "my/model"
    assert router.resolve("main", {"tokens": 999999}) == "my/model"


def test_a_big_context_moves_to_the_stronger_model():
    assert ModelRouter(_config()).resolve("main", {"tokens": 60000}) == "strong/model"


def test_many_turns_move_to_the_stronger_model():
    assert ModelRouter(_config()).resolve("main", {"turns": 31}) == "strong/model"


def test_a_small_context_keeps_the_main_model():
    assert ModelRouter(_config()).resolve("main", {"tokens": 100, "turns": 3}) == "main/model"


def test_a_tight_budget_moves_to_the_cheaper_model():
    context = {"tokens": 60000, "turns": 31, "cost": 0.85, "budget": 1.0}
    assert ModelRouter(_config()).resolve("main", context) == "cheap/model"


def test_a_budget_that_is_still_fine_keeps_the_stronger_model():
    context = {"tokens": 60000, "cost": 0.1, "budget": 1.0}
    assert ModelRouter(_config()).resolve("main", context) == "strong/model"


def test_a_tight_token_budget_moves_to_the_cheaper_model():
    """A model without a price spends no money, so the token budget is the budget."""
    context = {"tokens": 100, "cost": 0.0, "budget": 0.0, "token_budget": 1000, "tokens_used": 900}
    assert ModelRouter(_config()).resolve("main", context) == "cheap/model"


def test_a_token_budget_that_is_still_fine_keeps_the_main_model():
    context = {"tokens": 100, "cost": 0.0, "budget": 0.0, "token_budget": 1000, "tokens_used": 100}
    assert ModelRouter(_config()).resolve("main", context) == "main/model"


def test_a_rule_wins_over_the_default_policy():
    config = _config(routing_rules=[RoutingRuleConfig(when="calls > 5", purpose="cheap")])
    assert ModelRouter(config).resolve("main", {"calls": 6}) == "cheap/model"
    assert ModelRouter(config).resolve("main", {"calls": 2}) == "main/model"


def test_a_rule_that_does_not_hold_is_ignored():
    config = _config(routing_rules=[RoutingRuleConfig(when="calls > 5", purpose="cheap")])
    assert ModelRouter(config).resolve("main", {"other": 6}) == "main/model"


def test_a_broken_rule_is_ignored():
    config = _config(routing_rules=[RoutingRuleConfig(when="calls >", purpose="cheap")])
    assert ModelRouter(config).resolve("main", {"calls": 6}) == "main/model"


def test_a_rule_on_a_string_value_is_ignored():
    config = _config(routing_rules=[RoutingRuleConfig(when="state == done", purpose="cheap")])
    assert ModelRouter(config).resolve("main", {"state": "done"}) == "main/model"


def test_the_router_says_why_the_model_changed():
    router = ModelRouter(_config())
    assert "budget" in router.explain({"cost": 0.9, "budget": 1.0})
    assert "token budget" in router.explain({"token_budget": 1000, "tokens_used": 900})
    assert "context" in router.explain({"tokens": 60000})
    assert "turns" in router.explain({"turns": 40})


def test_the_loop_switches_the_model_and_says_so(tmp_path):
    """The change is in the event stream, so it can be read back later."""
    config = _config(
        model_name="scripted",
        routing_rules=[RoutingRuleConfig(when="turns > 0", purpose="cheap")],
    )
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    bus = EventBus()
    gateway = ModelGateway(ScriptedModel([{"role": "assistant", "content": "ok"}]))
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        gateway,
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
        router=ModelRouter(config, gateway),
    )
    loop.run_turn("hello")
    changes = [
        event
        for event in store.events(session.id)
        if event.type == EventType.STATE_CHANGE and event.payload.get("model")
    ]
    assert changes[0].payload["model"] == "cheap/model"
    assert changes[0].payload["previous"] == "scripted"
    assert changes[0].payload["reason"]


def _alias_file(tmp_path, alias: str, model: str) -> str:
    path = tmp_path / "litellm_config.yaml"
    path.write_text(
        f"model_list:\n  - model_name: {alias}\n    litellm_params:\n      model: {model}\n", encoding="utf-8"
    )
    return str(path)


def test_the_router_resolves_an_alias(tmp_path):
    config = _config(model_name="alias/model", litellm_config=_alias_file(tmp_path, "alias/model", "real/model"))
    assert ModelRouter(config).backend_for("alias/model").model_name == "real/model"


def test_the_loop_keeps_the_model_when_the_alias_is_the_same_one(tmp_path):
    """The alias of the model that is already in use is not a change."""
    config = _config(model_name="alias/scripted", litellm_config=_alias_file(tmp_path, "alias/scripted", "scripted"))
    store = SessionStore(tmp_path)
    session = store.create(tmp_path)
    bus = EventBus()
    model = ScriptedModel([{"role": "assistant", "content": "ok"}])
    gateway = ModelGateway(model)
    executor = build_executor(tmp_path)
    loop = AgentLoop(
        gateway,
        executor,
        session,
        store,
        bus,
        tools=executor.registry.schemas(),
        router=ModelRouter(config, gateway),
    )
    loop.run_turn("hello")
    assert loop.model.backend is model
    assert not [
        event
        for event in store.events(session.id)
        if event.type == EventType.STATE_CHANGE and event.payload.get("model")
    ]
