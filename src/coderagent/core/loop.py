"""The main loop: user input -> model -> tools -> model, until the model stops."""

import time
from dataclasses import dataclass, field

from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.protocols import ToolExecutor
from coderagent.core.session import Session, SessionState, SessionStore
from coderagent.models.gateway import ModelGateway


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


class AgentLoop:
    def __init__(
        self,
        model: ModelGateway,
        executor: ToolExecutor,
        session: Session,
        store: SessionStore,
        bus: EventBus,
        *,
        tools: list[dict] | None = None,
        system_prompt: str = "",
        max_turns: int = 50,
        cost_limit: float = 0.0,
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
        self.messages = self._restore_messages()

    def run(self, user_input: str) -> TurnResult:
        """Alias for `run_turn`; the caller drives the conversation."""
        return self.run_turn(user_input)

    def run_turn(self, user_input: str) -> TurnResult:
        """Run one turn: query the model, execute its tool calls, repeat until it stops."""
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        self.session.turn_count += 1
        self._publish(EventType.USER_MESSAGE, {"content": user_input})
        self._set_state(SessionState.THINKING)

        stop_reason = "end_turn"
        cost = 0.0
        n_calls = 0
        while True:
            if self.max_turns and n_calls >= self.max_turns:
                stop_reason = "max_turns"
                break
            if self.cost_limit and self.model.total_cost >= self.cost_limit:
                stop_reason = "cost_exceeded"
                break
            try:
                response = self.model.query(self._context(), tools=self.tools)
            except Exception as e:
                self._publish(EventType.ERROR, {"error": str(e)})
                stop_reason = "error"
                break
            n_calls += 1
            cost += response.get("extra", {}).get("cost", 0.0)
            self.messages.append(response)
            self._publish(
                EventType.ASSISTANT_MESSAGE,
                {"message": response, "cost": response.get("extra", {}).get("cost", 0.0)},
            )
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                break
            self._set_state(SessionState.EXECUTING)
            actions = self.executor.plan(tool_calls)
            self._publish(EventType.TOOL_CALL, {"actions": actions})
            observations = self.executor.execute(actions)
            self.messages.extend(observations)
            self._publish(EventType.TOOL_RESULT, {"messages": observations})
            self._set_state(SessionState.THINKING)

        self.session.total_cost = self.model.total_cost
        self._set_state(SessionState.DONE)
        return TurnResult(
            session_id=self.session.id,
            turn_count=self.session.turn_count,
            cost=cost,
            stop_reason=stop_reason,
            messages=self.messages[start:],
        )

    def _context(self) -> list[dict]:
        return ([{"role": "system", "content": self.system_prompt}] if self.system_prompt else []) + self.messages

    def _restore_messages(self) -> list[dict]:
        """Rebuild the conversation from the event log."""
        messages: list[dict] = []
        for event in self.store.events(self.session.id):
            if event.type == EventType.USER_MESSAGE:
                messages.append({"role": "user", "content": event.payload.get("content", "")})
            elif event.type == EventType.ASSISTANT_MESSAGE:
                messages.append(event.payload.get("message", {}))
            elif event.type == EventType.TOOL_RESULT:
                messages.extend(event.payload.get("messages", []))
        return messages

    def _publish(self, event_type: EventType, payload: dict) -> None:
        event = Event(type=event_type, session_id=self.session.id, timestamp=time.time(), payload=payload)
        self.bus.publish(event)
        self.store.append(self.session.id, event)

    def _set_state(self, state: SessionState) -> None:
        self.session.state = state
        self._publish(EventType.STATE_CHANGE, {"state": state.value})
