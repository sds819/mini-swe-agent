"""The main loop: user input -> model -> tools -> model, until the model stops."""

import time
from dataclasses import dataclass, field

from coderagent.config.schema import ContextConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.protocols import ToolExecutor
from coderagent.core.session import Session, SessionState, SessionStore
from coderagent.models.gateway import ModelGateway, is_context_overflow


@dataclass
class TurnResult:
    session_id: str
    turn_count: int
    """Number of user-initiated turns in this session so far."""
    cost: float
    stop_reason: str
    """One of `end_turn`, `max_turns`, `cost_exceeded`, `error`."""
    messages: list[dict] = field(default_factory=list)
    """Messages added during this turn."""
    error: str = ""
    """Why the turn stopped, if it stopped because of an error."""


class AgentLoop:
    def __init__(
        self,
        model: ModelGateway,
        executor: ToolExecutor,
        session: Session,
        store: SessionStore,
        bus: EventBus,
        *,
        context: ContextEngine | None = None,
        tools: list[dict] | None = None,
        system_prompt: str = "",
        max_turns: int = 50,
        cost_limit: float = 0.0,
        checkpoints=None,
    ) -> None:
        self.model = model
        self.executor = executor
        self.session = session
        self.store = store
        self.bus = bus
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.cost_limit = cost_limit
        self.checkpoints = checkpoints
        self.context = context or ContextEngine(
            session, store, bus, ContextConfig(), model, system_prompt=system_prompt, cwd=session.cwd
        )
        self.context.system_prompt = system_prompt or self.context.system_prompt
        self.context.restore()

    @property
    def messages(self) -> list[dict]:
        return self.context.history.messages

    def run(self, user_input: str) -> TurnResult:
        """Alias for `run_turn`; the caller drives the conversation."""
        return self.run_turn(user_input)

    def run_turn(self, user_input: str) -> TurnResult:
        """Run one turn: query the model, execute its tool calls, repeat until it stops."""
        turn_messages: list[dict] = []
        self.context.append({"role": "user", "content": user_input})
        turn_messages.append({"role": "user", "content": user_input})
        self.session.turn_count += 1
        self._set_state(SessionState.THINKING)

        stop_reason = "end_turn"
        error = ""
        cost = 0.0
        n_calls = 0
        while True:
            if self.max_turns and n_calls >= self.max_turns:
                stop_reason = "max_turns"
                break
            if self.cost_limit and self.model.total_cost >= self.cost_limit:
                stop_reason = "cost_exceeded"
                break
            self.context.maybe_compact()
            response, error = self._query()
            if response is None:
                self._publish(EventType.ERROR, {"error": error})
                stop_reason = "error"
                break
            n_calls += 1
            cost += response.get("extra", {}).get("cost", 0.0)
            self.context.append(response)
            turn_messages.append(response)
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                break
            self._set_state(SessionState.EXECUTING)
            actions = self.executor.plan(tool_calls)
            self._publish(EventType.TOOL_CALL, {"actions": actions})
            observations = self.executor.execute(actions)
            self.context.extend(observations)
            turn_messages.extend(observations)
            self._set_state(SessionState.THINKING)

        self.session.total_cost = self.model.total_cost
        self._set_state(SessionState.ERROR if stop_reason == "error" else SessionState.DONE)
        return TurnResult(
            session_id=self.session.id,
            turn_count=self.session.turn_count,
            cost=cost,
            stop_reason=stop_reason,
            messages=turn_messages,
            error=error,
        )

    def _query(self) -> tuple[dict | None, str]:
        """Ask the model. When the provider says the context is too big, compact and try once more."""
        try:
            return self.model.query(self.context.build_messages(tools=self.tools), tools=self.tools), ""
        except Exception as e:
            if not is_context_overflow(e):
                return None, f"{type(e).__name__}: {e}"
            if not self.context.force_compact():
                return None, f"{type(e).__name__}: {e} (nothing left to compact)"
            try:
                return self.model.query(self.context.build_messages(tools=self.tools), tools=self.tools), ""
            except Exception as retry_error:
                return None, f"{type(retry_error).__name__}: {retry_error}"

    def _publish(self, event_type: EventType, payload: dict) -> None:
        event = Event(type=event_type, session_id=self.session.id, timestamp=time.time(), payload=payload)
        self.bus.publish(event)
        self.store.append(self.session.id, event)

    def _set_state(self, state: SessionState) -> None:
        self.session.state = state
        self._publish(EventType.STATE_CHANGE, {"state": state.value})
