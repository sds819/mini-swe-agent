"""Assembly of the coding agent: config -> model -> environment -> session -> loop."""

from pathlib import Path

from coderagent.config.schema import Config
from coderagent.core.bash_adapter import BashExecutor
from coderagent.core.events import EventBus
from coderagent.core.loop import AgentLoop, TurnResult
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import SessionStore
from coderagent.models.backends import LiteLLMBackend
from coderagent.models.gateway import ModelGateway
from minisweagent.models.utils.actions_toolcall import BASH_TOOL


def build_model(config: Config) -> ModelBackend:
    return LiteLLMBackend(
        config.model.model_name,
        model_kwargs=config.model.model_kwargs,
        set_cache_control=config.model.set_cache_control,
    )


def build_loop(
    config: Config,
    cwd: Path,
    *,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
) -> AgentLoop:
    store = store or SessionStore()
    session = store.create(cwd)
    return AgentLoop(
        ModelGateway(model if model is not None else build_model(config)),
        BashExecutor(cwd=str(cwd), timeout=config.tools.bash_timeout),
        session,
        store,
        EventBus(),
        tools=[BASH_TOOL],
        system_prompt=config.agent.system_prompt,
        max_turns=config.agent.max_turns,
        cost_limit=config.agent.cost_limit,
    )


def run_turn(
    task: str,
    config: Config,
    *,
    cwd: Path,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
) -> TurnResult:
    return build_loop(config, cwd, model=model, store=store).run_turn(task)
