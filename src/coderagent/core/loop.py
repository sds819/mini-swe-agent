"""The main loop: user input -> model -> tools -> model, until the model stops."""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from coderagent.config.schema import ContextConfig
from coderagent.core.context import ContextEngine
from coderagent.core.events import Event, EventBus, EventType
from coderagent.core.protocols import ToolExecutor
from coderagent.core.session import Session, SessionState, SessionStore
from coderagent.models.gateway import ModelGateway, is_context_overflow
from coderagent.models.streaming import ModelEvent, message_from_events


@dataclass
class TurnResult:
    session_id: str
    turn_count: int
    """Number of user-initiated turns in this session so far."""
    cost: float
    """What this turn cost."""
    stop_reason: str
    """One of `end_turn`, `max_turns`, `cost_exceeded`, `error`."""
    messages: list[dict] = field(default_factory=list)
    """Messages added during this turn."""
    error: str = ""
    """Why the turn stopped, if it stopped because of an error."""
    session_cost: float = 0.0
    """What the whole session cost, the turns before this one and the reflection included."""


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
        hooks=None,
        mcp=None,
        subagents=None,
        router=None,
        plugins=None,
        sandbox=None,
        schema_budget: int | None = None,
    ) -> None:
        self.model = model
        self.executor = executor
        self.policy = executor.policy
        """The permission policy of the session. `/mode` changes it under us."""
        self.session = session
        self.store = store
        self.bus = bus
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.cost_limit = cost_limit
        self.checkpoints = checkpoints
        self.hooks = hooks
        """The hook runner, when the session has hooks."""
        self.mcp = mcp
        """The MCP manager, when the session has servers."""
        self.subagents = subagents or {}
        """The sub agents that are available, by name."""
        self.router = router
        """The model router, when the session has one."""
        self.plugins = plugins or []
        """The plugins that were loaded, by name."""
        self.sandbox = sandbox
        """The environment the commands run in."""
        self.schema_budget = schema_budget
        """The tokens the schemas of the tools may take. None means no limit."""
        self.cancel = None
        """A callable that says whether the turn should stop. The interface sets it."""
        self.context = context or ContextEngine(
            session,
            store,
            bus,
            ContextConfig(),
            model,
            system_prompt=system_prompt,
            cwd=session.cwd,
            policy=self.policy,
        )
        self.context.system_prompt = system_prompt or self.context.system_prompt
        self.context.restore()
        self._session_start()

    @property
    def messages(self) -> list[dict]:
        return self.context.history.messages

    def switch_to(self, session: Session) -> None:
        """Continue in another session, with the history that session already has."""
        self.session = session
        self.context = ContextEngine(
            session,
            self.store,
            self.bus,
            self.context.config,
            self.model,
            system_prompt=self.system_prompt,
            memory_config=self.context.memory_config,
            summary_model=self.context.summary_model,
            cwd=session.cwd,
            policy=self.policy,
        )
        self.context.restore()
        self._session_start()

    def run(self, user_input: str) -> TurnResult:
        """Alias for `run_turn`; the caller drives the conversation."""
        return self.run_turn(user_input)

    def run_turn(self, user_input: str) -> TurnResult:
        """Run one turn: query the model, execute its tool calls, repeat until it stops."""
        turn_messages: list[dict] = []
        prompt = user_input
        original = ""
        if self.hooks:
            hook = self.hooks.apply("UserPromptSubmit", {"prompt": user_input})
            if hook.blocked:
                reason = hook.reason or "the prompt was blocked"
                self._publish(EventType.ERROR, {"error": reason})
                self._publish(EventType.TURN_END, {"stop_reason": "error", "error": reason, "calls": 0, "cost": 0.0})
                return TurnResult(
                    session_id=self.session.id,
                    turn_count=self.session.turn_count,
                    cost=0.0,
                    stop_reason="error",
                    error=reason,
                )
            if isinstance(hook.updated_input, str):
                """The hook rewrote the prompt. What the user typed is kept aside."""
                prompt = hook.updated_input
                original = user_input
            if hook.additional_context:
                prompt = f"{prompt}\n\n[hook] {hook.additional_context}"
        self.context.append({"role": "user", "content": prompt}, original=original)
        turn_messages.append({"role": "user", "content": prompt})
        self.session.turn_count += 1
        self._set_state(SessionState.THINKING)

        stop_reason = "end_turn"
        error = ""
        cost = 0.0
        n_calls = 0
        stop_blocks = 0
        base = self.session.total_cost
        before = self.model.total_cost
        while True:
            # The tools of the last round may have spent money too.
            before = self._bill(before)
            if self.cancel is not None and self.cancel():
                stop_reason = "interrupted"
                break
            if self.max_turns and n_calls >= self.max_turns:
                stop_reason = "max_turns"
                break
            if self.cost_limit and self.session.total_cost >= self.cost_limit:
                stop_reason = "cost_exceeded"
                break
            self.context.maybe_compact()
            self._route()
            response, error = self._query()
            before = self._bill(before)
            if response is None:
                self._publish(EventType.ERROR, {"error": error})
                stop_reason = "error"
                break
            n_calls += 1
            response.setdefault("extra", {}).update(
                {"purpose": "main", "model": getattr(self.model.backend, "model_name", "")}
            )
            self.context.append(response)
            turn_messages.append(response)
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                if stop_blocks < 3 and self._stop_blocked(response):
                    stop_blocks += 1
                    continue
                break
            self._set_state(SessionState.EXECUTING)
            actions = self.executor.plan(tool_calls)
            self._publish(EventType.TOOL_CALL, {"actions": actions})
            observations = self.executor.execute(actions)
            self.context.extend(observations)
            turn_messages.extend(observations)
            self._set_state(SessionState.THINKING)

        # What the turn cost: everything the agent spent, the sub agents and the summaries included.
        cost = self.session.total_cost - base
        self._publish(
            EventType.TURN_END,
            {"stop_reason": stop_reason, "error": error, "calls": n_calls, "cost": cost},
        )
        self._set_state(SessionState.ERROR if stop_reason == "error" else SessionState.DONE, stop_reason=stop_reason)
        self._session_end()
        return TurnResult(
            session_id=self.session.id,
            turn_count=self.session.turn_count,
            cost=cost,
            stop_reason=stop_reason,
            messages=turn_messages,
            error=error,
        )

    def _bill(self, before: float) -> float:
        """Put what the gateway spent on the bill of this session.

        The gateway is shared by all the sessions of the process, the bill is not: a
        session pays for its own calls only.
        """
        self.session.total_cost += self.model.total_cost - before
        return self.model.total_cost

    def _route(self) -> None:
        """Pick the model of this turn. A change is announced in the event stream."""
        if self.router is None:
            return
        name = self.router.resolve("main", self._routing_context())
        if not name:
            return
        backend = self.router.backend_for(name)
        current = getattr(self.model.backend, "model_name", "")
        if backend.model_name == current:
            """The same model behind another name. There is nothing to change."""
            return
        self.model.backend = backend
        self._publish(
            EventType.STATE_CHANGE,
            {
                "state": self.session.state.value,
                "model": name,
                "previous": current,
                "reason": self._route_reason(),
            },
        )

    def _routing_context(self) -> dict:
        """What the router knows about the session."""
        return {
            "tokens": self.context.estimated_tokens(self.tools),
            "turns": self.session.turn_count,
            "calls": self.model.n_calls,
            "cost": self.session.total_cost,
            "budget": self.cost_limit,
        }

    def _route_reason(self) -> str:
        """Why the model changed, in one line."""
        return self.router.explain(self._routing_context())

    def _stop_blocked(self, response: dict) -> bool:
        """Ask the Stop hook whether the agent may stop. A blocked stop means: keep going."""
        if not self.hooks:
            return False
        hook = self.hooks.apply("Stop", {"last_message": response.get("content", "")})
        if not hook.blocked:
            return False
        self.context.append({"role": "user", "content": f"[hook] {hook.reason}"})
        return True

    def _session_start(self) -> None:
        if self.hooks:
            self.hooks.apply("SessionStart", {"session_id": self.session.id, "cwd": str(self.session.cwd)})

    def _session_end(self) -> None:
        if self.hooks:
            self.hooks.apply(
                "SessionEnd",
                {"session_id": self.session.id, "turns": self.session.turn_count, "cost": self.session.total_cost},
            )

    def _query(self) -> tuple[dict | None, str]:
        """Ask the model. When the provider says the context is too big, compact and try once more."""
        try:
            return self._collect(), ""
        except Exception as e:
            if not is_context_overflow(e):
                return None, f"{type(e).__name__}: {e}"
            if not self.context.force_compact():
                return None, f"{type(e).__name__}: {e} (nothing left to compact)"
            try:
                return self._collect(), ""
            except Exception as retry_error:
                return None, f"{type(retry_error).__name__}: {retry_error}"

    def _collect(self) -> dict:
        """Read the answer as it arrives and fold it into one message."""
        events = self.model.query_stream(self.context.build_messages(tools=self.tools), tools=self.tools)
        return message_from_events(self._announce(events))

    def _announce(self, events) -> Iterator[ModelEvent]:
        """Publish the pieces of the answer, so the UI can show them while they arrive."""
        for event in events:
            if event.type == "text":
                self._notify(EventType.TEXT_DELTA, {"content": event.content})
            elif event.type == "reasoning":
                self._notify(EventType.REASONING, {"content": event.content})
            yield event

    def _notify(self, event_type: EventType, payload: dict) -> None:
        """Publish to the UI only. The event log keeps the whole messages."""
        self.bus.publish(Event(type=event_type, session_id=self.session.id, timestamp=time.time(), payload=payload))

    def _publish(self, event_type: EventType, payload: dict) -> None:
        event = Event(type=event_type, session_id=self.session.id, timestamp=time.time(), payload=payload)
        self.bus.publish(event)
        self.store.append(self.session.id, event)

    def _set_state(self, state: SessionState, **extra) -> None:
        self.session.state = state
        self._publish(EventType.STATE_CHANGE, {"state": state.value, **extra})
