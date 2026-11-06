"""Configuration schema. See `docs/design/coding-agent-architecture.md` section 7."""

from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in a code repository. "
    "Prefer the dedicated tools over shell commands: `read` to look at a file, `glob`/`grep`/`ls` to find code, "
    "`edit`/`multi_edit` to change files, and `bash` for builds, tests and pipelines. "
    "Complete the task the user describes and summarize what you changed."
)

BUILTIN_TOOL_NAMES = [
    "read",
    "write",
    "edit",
    "multi_edit",
    "glob",
    "grep",
    "ls",
    "bash",
    "bash_output",
    "bash_kill",
    "todo_write",
    "task",
]


class ModelConfig(BaseModel):
    model_name: str = ""
    """Model name. Falls back to $MSWEA_MODEL_NAME and then to a built-in default."""
    model_kwargs: dict = Field(default_factory=dict)
    max_retries: int = 3
    routing: dict[str, str] = Field(default_factory=dict)
    set_cache_control: str | None = None


class AgentConfig(BaseModel):
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 50
    """Maximum number of model calls per user turn. 0 means no limit."""
    cost_limit: float = 0.0
    """Stop after exceeding this cost. 0 means no limit."""


class ToolConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: list(BUILTIN_TOOL_NAMES))
    """Names of the tools the model may call."""
    disabled: list[str] = Field(default_factory=list)
    bash_timeout: int = 120
    max_output_tokens: int = 8000


class PermissionConfig(BaseModel):
    mode: str = "default"
    """One of default, acceptEdits, plan, bypass, readonly."""
    rules: list[dict] = Field(default_factory=list)
    deny_paths: list[str] = Field(default_factory=list)
    include_dirs: list[str] = Field(default_factory=list)
    """Directories outside the working directory that the agent may still touch."""


class ContextConfig(BaseModel):
    context_window: int = 200000
    reserved_output: int = 8000
    compact_threshold: float = 0.8
    keep_recent_turns: int = 20
    keep_recent_token_ratio: float = 0.4
    compact_every_turns: int = 40
    auto_compact: bool = True
    summarize_model: str = ""
    """Model used for summarization. Empty means the same model as the agent."""


class MemoryConfig(BaseModel):
    project_path: str = ".coderagent/memory"
    user_path: str = "~/.coderagent/CLAUDE.md"
    enabled: bool = True


class CheckpointConfig(BaseModel):
    enabled: bool = True
    keep: int = 50


class MCPServerConfig(BaseModel):
    name: str
    command: str = ""
    """Command that starts the server, for the stdio transport."""
    url: str = ""
    """Address of the server, for the http transport."""
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPConfig(BaseModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)
    timeout: int = 30


class HookCommand(BaseModel):
    type: str = "command"
    command: str
    timeout: int = 10
    strict: bool = False
    """When the hook fails, block the action instead of letting it through."""


class HookMatcher(BaseModel):
    matcher: str = ""
    """Regular expression of the tool names this hook applies to. Empty means all."""
    hooks: list[HookCommand] = Field(default_factory=list)


class HookConfig(BaseModel):
    events: dict[str, list[HookMatcher]] = Field(default_factory=dict)


class UIConfig(BaseModel):
    theme: str = "auto"
    show_reasoning: bool = True
    approval_timeout: int = 0
    """Seconds to wait for an approval. 0 waits forever."""


class SandboxConfig(BaseModel):
    type: str = "local"
    network: str = "restricted"
    writable_roots: list[str] = Field(default_factory=lambda: ["."])


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    hooks: HookConfig = Field(default_factory=HookConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    cwd: Path = Field(default_factory=Path.cwd)
