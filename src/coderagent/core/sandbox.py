"""The sandbox: the place where the commands of the agent run.

The local sandbox runs the commands on the machine of the user. The other
sandboxes are the ones of mini-swe-agent: a Docker container through SWE-ReX,
Modal, bubblewrap or contree. They are chosen with `sandbox.type` in the
configuration:

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
```

The options that the environment does not know are ignored.
"""

from pathlib import Path
from typing import Any

from coderagent.config.schema import SandboxConfig
from coderagent.tools.builtin.shell import CodingEnvironment

LOCAL = "local"


def build_environment(config: SandboxConfig, cwd: Path) -> Any:
    """The environment of the session."""
    if config.type == LOCAL:
        return CodingEnvironment(cwd=str(cwd))
    from minisweagent.environments import get_environment

    options = config.model_dump(exclude={"type"})
    options["cwd"] = str(cwd)
    environment = get_environment(options, default_type=config.type)
    if hasattr(environment, "_check_finished"):
        """A coding agent ends a turn when the model says so, not when a command prints a sentinel."""
        environment._check_finished = lambda output: None
    return environment


def describe(environment: Any, kind: str = "") -> str:
    """The name of the environment, for the interface."""
    if kind:
        return kind
    if environment is None or isinstance(environment, CodingEnvironment):
        return LOCAL
    return type(environment).__name__


__all__ = ["LOCAL", "build_environment", "describe"]
