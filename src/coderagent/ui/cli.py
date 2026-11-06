"""Command line interface."""

from pathlib import Path

import litellm
import typer

from coderagent.config.loader import load_config
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import SessionStore
from coderagent.run import run_turn
from coderagent.ui.render import render

# litellm prints debug banners to stdout; the CLI owns stdout for machine-readable output.
litellm.suppress_debug_info = True

app = typer.Typer(rich_markup_mode="rich")


def main_impl(
    task: str,
    config,
    cwd: Path,
    output_format: str = "text",
    *,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    permission_mode: str | None = None,
) -> str:
    """Run one turn and render the result."""
    return render(
        run_turn(task, config, cwd=cwd, model=model, store=store, permission_mode=permission_mode), output_format
    )


# fmt: off
@app.command()
def main(
    task: str = typer.Option("", "-t", "--task", help="Task/problem statement"),
    model_name: str = typer.Option("", "-m", "--model", help="Model to use"),
    config_spec: list[str] = typer.Option([], "-c", "--config", help="Config file or key=value overrides"),
    print_mode: bool = typer.Option(False, "--print", help="Non-interactive mode (the only mode in M0)"),
    output_format: str = typer.Option("text", "--output-format", help="text|json"),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory of the session"),
    permission_mode: str = typer.Option("", "--permission-mode", help="default|acceptEdits|plan|bypass|readonly"),
) -> None:
    # fmt: on
    config = load_config(config_spec, cwd=cwd)
    if model_name:
        config.model.model_name = model_name
    typer.echo(main_impl(task, config, cwd, output_format, permission_mode=permission_mode or None))
