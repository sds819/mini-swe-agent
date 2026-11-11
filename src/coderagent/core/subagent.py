"""Sub agents: a task that runs in its own context and returns a conclusion.

A sub agent is defined by a markdown file in `.coderagent/agents`:

    ---
    name: code-explorer
    description: Locate a symbol and explain the code around it.
    tools: [read, grep, glob, ls]
    model_purpose: cheap
    max_turns: 15
    ---
    You are a code base explorer. ...

The body is the system prompt of the sub agent. The tools are a white list: the
sub agent cannot reach anything else. The messages live only in the sub agent, so
the context of the main agent stays clean.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from coderagent.core.events import EventBus
from coderagent.paths import config_home
from coderagent.tools.executor import ToolExecutor
from coderagent.tools.permissions import mode_block
from coderagent.tools.registry import ToolRegistry

AGENTS_DIR = "agents"
"""The directory of the sub agents. In the project it is under `.coderagent`."""

DEFAULT_TOOLS = ["read", "grep", "glob", "bash"]

BUILTIN_SUBAGENTS: dict[str, "SubagentSpec"] = {}
"""The sub agents that are always there. Filled at the end of this module."""


@dataclass
class SubagentSpec:
    """What a sub agent is and what it may do."""

    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))
    model_purpose: str = "cheap"
    max_turns: int = 20
    path: Path | None = None

    def render(self) -> str:
        """The description, as the main agent sees it."""
        return f"{self.name}: {self.description}" if self.description else self.name


def parse_subagent(path: Path) -> SubagentSpec | None:
    """Read one sub agent file. Returns None when the file cannot be used."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    _, _, rest = text.partition("---")
    front_matter, _, body = rest.partition("---")
    try:
        data = yaml.safe_load(front_matter) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return SubagentSpec(
        name=str(data.get("name") or path.stem),
        description=str(data.get("description", "")),
        system_prompt=body.strip(),
        tools=_tool_list(data.get("tools")),
        model_purpose=str(data.get("model_purpose", "cheap")),
        max_turns=int(data.get("max_turns", 20)),
        path=path,
    )


def _tool_list(value) -> list[str]:
    """The white list of the tools. Empty means the default set."""
    if value is None:
        return list(DEFAULT_TOOLS)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def load_subagents(cwd: Path, user_home: Path | None = None) -> dict[str, SubagentSpec]:
    """The sub agents of the project and of the user. The project wins on a name clash."""
    specs: dict[str, SubagentSpec] = dict(BUILTIN_SUBAGENTS)
    for directory in _directories(cwd, user_home):
        for path in sorted(directory.glob("*.md")):
            spec = parse_subagent(path)
            if spec is not None:
                specs[spec.name] = spec
    return specs


def _directories(cwd: Path, user_home: Path | None) -> list[Path]:
    home = Path(user_home) if user_home else config_home()
    directories = [home / AGENTS_DIR, Path(cwd) / ".coderagent" / AGENTS_DIR]
    return [directory for directory in directories if directory.is_dir()]


class SubAgentRunner:
    """Runs a sub agent: its own messages, its own tools, its own turn budget."""

    def __init__(
        self,
        gateway,
        registry: ToolRegistry,
        policy,
        ctx_factory,
        *,
        approver=None,
        gateway_for=None,
        bus: EventBus | None = None,
        session_id: str = "",
        hooks=None,
        before_write=None,
        store=None,
        on_path=None,
        schema_budget: int | None = None,
    ) -> None:
        self.gateway = gateway
        self.registry = registry
        self.policy = policy
        self.ctx_factory = ctx_factory
        self.approver = approver
        self.gateway_for = gateway_for
        """Returns the gateway of a purpose. The main gateway when it is not set."""
        self.bus = bus
        self.session_id = session_id
        self.hooks = hooks
        """The hook runner of the session. The sub agent goes through the same hooks."""
        self.before_write = before_write
        """Called before a write tool changes a file, e.g. to take a checkpoint."""
        self.store = store
        """The event log. The result of a tool of the sub agent lands in it."""
        self.on_path = on_path
        """Called with the path of every path based tool."""
        self.schema_budget = schema_budget
        """The tokens the schemas of the tools may take. None means no limit."""

    def run(self, spec: SubagentSpec, description: str, prompt: str) -> dict:
        """Run the sub agent and return the structured result."""
        registry = self._restricted(spec)
        executor = ToolExecutor(
            registry,
            self.policy,
            self.ctx_factory,
            self.approver,
            hooks=self.hooks,
            before_write=self.before_write,
            store=self.store,
            on_path=self.on_path,
        )
        gateway = self._gateway(spec)
        before = (gateway.total_cost, gateway.total_tokens_in, gateway.total_tokens_out)
        system = spec.system_prompt or spec.description
        block = mode_block(self.policy.mode)
        if block:
            """The sub agent shares the permission mode, so it has to know about it too."""
            system = f"{system}\n\n{block}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{description}\n\n{prompt}".strip()},
        ]
        schemas = registry.schemas(self.schema_budget)
        turns = 0
        touched: list[str] = []
        summary = ""
        status = "completed"
        while turns < spec.max_turns:
            try:
                response = gateway.query(messages, tools=schemas)
            except Exception as e:
                return self._result("error", f"{type(e).__name__}: {e}", [], [], gateway, before, turns)
            turns += 1
            messages.append(response)
            summary = response.get("content", "") or summary
            calls = response.get("tool_calls") or []
            touched += _paths_of(calls)
            if not calls:
                break
            actions = executor.plan(calls)
            self._publish(actions)
            messages.extend(executor.execute(actions))
        else:
            status = "max_turns"
        return self._result(status, summary, _findings(summary), touched, gateway, before, turns)

    def _restricted(self, spec: SubagentSpec) -> ToolRegistry:
        """The registry with only the tools of the white list."""
        tools = [self.registry.get(name) for name in spec.tools]
        return ToolRegistry([tool for tool in tools if tool is not None])

    def _gateway(self, spec: SubagentSpec):
        if self.gateway_for is None:
            return self.gateway
        return self.gateway_for(spec.model_purpose) or self.gateway

    def _publish(self, actions: list[dict]) -> None:
        """Let the interface know what the sub agent does."""
        if self.bus is None:
            return
        from coderagent.core.events import Event, EventType

        self.bus.publish(
            Event(
                type=EventType.TOOL_CALL,
                session_id=self.session_id,
                timestamp=0.0,
                payload={"actions": actions},
            )
        )

    def _result(
        self, status: str, summary: str, findings: list[str], touched: list[str], gateway, before, turns: int
    ) -> dict:
        """What the sub agent spent. When it ran on its own model, the cost is booked on the main one."""
        cost = gateway.total_cost - before[0]
        tokens_in = gateway.total_tokens_in - before[1]
        tokens_out = gateway.total_tokens_out - before[2]
        if gateway is not self.gateway:
            self.gateway.total_cost += cost
            self.gateway.total_tokens_in += tokens_in
            self.gateway.total_tokens_out += tokens_out
        return {
            "status": status,
            "summary": summary,
            "findings": findings,
            "files_touched": sorted(set(touched)),
            "cost": cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "turns": turns,
        }


def _paths_of(calls: list[dict]) -> list[str]:
    """The files the tool calls touch."""
    paths = []
    for call in calls:
        function = call.get("function") or {}
        name = function.get("name", "")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                continue
        if not isinstance(arguments, dict):
            continue
        path = arguments.get("path")
        if path and name in ("write", "edit", "multi_edit"):
            paths.append(str(path))
    return paths


def _findings(summary: str) -> list[str]:
    """The bullet points of the conclusion."""
    return [line.lstrip("-* ").strip() for line in summary.splitlines() if line.strip().startswith(("-", "*"))]


def render_result(result: dict) -> str:
    """The result of a sub agent, as the main agent reads it."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def subagent_index(specs: dict[str, SubagentSpec]) -> str:
    """The index of the sub agents, as it goes into the system prompt."""
    if not specs:
        return ""
    lines = [
        "<subagents>",
        "These sub agents are available. Hand a job to one with the `task` tool.",
        *[f"- {spec.render()}" for spec in specs.values()],
        "</subagents>",
    ]
    return "\n".join(lines)


__all__ = [
    "BUILTIN_SUBAGENTS",
    "SubAgentRunner",
    "SubagentSpec",
    "load_subagents",
    "parse_subagent",
    "render_result",
    "subagent_index",
]

BUILTIN_SUBAGENTS.update(
    {
        "code-explorer": SubagentSpec(
            name="code-explorer",
            description="Find code: locate a symbol, follow a call chain, explain how a part works.",
            system_prompt=(
                "You are a code base explorer. Given a target (a symbol, a behaviour or a question), "
                "find the code that matters:\n"
                "1. Narrow the search down with grep and glob.\n"
                "2. Read the files that matter.\n"
                "3. Answer with the files and the line numbers, the relations between them and your judgement.\n\n"
                "Never change a file. Answer with a short summary and a bullet point per finding."
            ),
            tools=["read", "grep", "glob", "ls"],
            model_purpose="cheap",
            max_turns=15,
        ),
        "verifier": SubagentSpec(
            name="verifier",
            description="Check a result on its own: run the tests, reproduce the bug.",
            system_prompt=(
                "You are a verifier. You do not trust the claims of others, you check them.\n"
                "1. Reproduce the situation: run the tests, the build or the command that fails.\n"
                "2. Read the code that is involved.\n"
                "3. Say what is true: does it work, and what exactly is broken when it does not.\n\n"
                "Never change a file unless the job asks for it. Answer with a short summary and a "
                "bullet point per finding."
            ),
            tools=["read", "grep", "glob", "bash"],
            model_purpose="main",
            max_turns=20,
        ),
        "refactorer": SubagentSpec(
            name="refactorer",
            description="Change the same pattern everywhere: a rename, a moved helper, a new signature.",
            system_prompt=(
                "You are a refactorer. You make the same change everywhere it is needed and nowhere else.\n"
                "1. Find every place the pattern occurs.\n"
                "2. Change them one by one.\n"
                "3. Run the tests when there are any.\n\n"
                "Answer with a short summary, a bullet point per place you changed and the tests you ran."
            ),
            tools=["read", "edit", "grep", "glob"],
            model_purpose="main",
            max_turns=30,
        ),
    }
)
