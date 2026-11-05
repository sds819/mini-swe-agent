"""Configuration schema. See `docs/design/coding-agent-architecture.md` section 7."""

from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent. Use the bash tool to inspect and change the codebase. "
    "Complete the task the user describes and summarize what you changed."
)


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
    enabled: list[str] = Field(default_factory=lambda: ["bash"])
    bash_timeout: int = 120
    max_output_tokens: int = 8000


class PermissionConfig(BaseModel):
    mode: str = "default"
    rules: list[dict] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    type: str = "local"
    network: str = "restricted"
    writable_roots: list[str] = Field(default_factory=lambda: ["."])


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    cwd: Path = Field(default_factory=Path.cwd)
