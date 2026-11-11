"""Command line interface."""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import litellm
import typer

from coderagent.config.loader import load_config
from coderagent.core.protocols import ModelBackend
from coderagent.core.session import Session, SessionStore
from coderagent.run import build_loop, run_turn
from coderagent.ui.render import render

# litellm prints debug banners to stdout; the CLI owns stdout for machine-readable output.
litellm.suppress_debug_info = True

app = typer.Typer(rich_markup_mode="rich", invoke_without_command=True, no_args_is_help=False)


def main_impl(
    task: str,
    config,
    cwd: Path,
    output_format: str = "text",
    *,
    model: ModelBackend | None = None,
    store: SessionStore | None = None,
    session: Session | None = None,
    permission_mode: str | None = None,
) -> str:
    """Run one turn and render the result."""
    return render(
        run_turn(task, config, cwd=cwd, model=model, store=store, session=session, permission_mode=permission_mode),
        output_format,
    )


def pick_session(
    store: SessionStore, cwd: Path, resume: str = "", continue_last: bool = False, fork: str = ""
) -> Session | None:
    """The session the turn should continue in. `None` means: start a new one."""
    if resume:
        return store.rebuild(resume)
    if fork:
        return store.fork(fork)
    if continue_last:
        sessions = store.list(cwd)
        return sessions[0] if sessions else None
    return None


def run_command(task: str, config, cwd: Path, store: SessionStore, session: Session | None) -> None:
    """Run a slash command instead of a turn."""
    from coderagent.ui.commands import CommandContext, run

    loop = build_loop(config, cwd, store=store, session=session)
    context = CommandContext(
        loop=loop,
        session=loop.session,
        store=store,
        bus=loop.bus,
        cwd=cwd,
        config=config,
        policy=loop.executor.policy,
        checkpoints=loop.checkpoints,
        mcp=loop.mcp,
        output=typer.echo,
        quit=lambda: None,
    )
    run(context, task)


def render_sessions(sessions: list[Session], output_format: str = "text") -> str:
    """The session list, as text or as json."""
    if output_format == "json":
        import json

        return json.dumps(
            [
                {
                    "id": session.id,
                    "cwd": str(session.cwd),
                    "created_at": session.created_at,
                    "turns": session.turn_count,
                    "cost": session.total_cost,
                }
                for session in sessions
            ],
            ensure_ascii=False,
            indent=2,
        )
    if not sessions:
        return "no sessions yet"
    return "\n".join(
        f"{session.id}  {session.turn_count:>3} turns  ${session.total_cost:.4f}  {session.cwd}" for session in sessions
    )


# fmt: off
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    task: str = typer.Option("", "-t", "--task", help="Task/problem statement"),
    model_name: str = typer.Option("", "-m", "--model", help="Model to use"),
    config_spec: list[str] = typer.Option([], "-c", "--config", help="Config file or key=value overrides"),
    print_mode: bool = typer.Option(False, "--print", help="Non-interactive mode (the only mode in M0)"),
    output_format: str = typer.Option("text", "--output-format", help="text|json"),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory of the session"),
    permission_mode: str = typer.Option("", "--permission-mode", help="default|acceptEdits|plan|bypass|readonly"),
    resume: str = typer.Option("", "--resume", help="Continue the session with this id"),
    continue_last: bool = typer.Option(False, "--continue", help="Continue the last session of this directory"),
    fork: str = typer.Option("", "--fork", help="Copy the session with this id and continue in the copy"),
    list_sessions: bool = typer.Option(False, "--list", help="List the sessions of this directory"),
    tui: bool = typer.Option(False, "--tui", help="Start the terminal interface"),
) -> None:
    # fmt: on
    if ctx.invoked_subcommand is not None:
        return
    config = load_config(config_spec, cwd=cwd)
    if model_name:
        config.model.model_name = model_name
    store = SessionStore()
    if list_sessions:
        typer.echo(render_sessions(store.list(cwd), output_format))
        return
    session = pick_session(store, cwd, resume, continue_last, fork)
    if not task:
        if tui or sys.stdin.isatty():
            from coderagent.ui.tui import main as run_tui

            run_tui(config, cwd, store=store, session=session)
            return
        typer.echo(f"session {session.id}" if session else "no task given")
        return
    if task.startswith("/"):
        run_command(task, config, cwd, store, session)
        return
    typer.echo(main_impl(task, config, cwd, output_format, store=store, session=session, permission_mode=permission_mode or None))


@app.command()
def web(
    cwd: Path = typer.Option(Path("."), "--cwd", help="The directory the agent works in"),
    host: str = typer.Option("127.0.0.1", "--host", help="The address to listen on"),
    port: int = typer.Option(8765, "--port", help="The port to listen on"),
    config_spec: list[str] = typer.Option([], "-c", "--config", help="Config file or key=value overrides"),
    model_name: str = typer.Option("", "-m", "--model", help="Model to use"),
    permission_mode: str = typer.Option("", "--permission-mode", help="default|acceptEdits|plan|bypass|readonly"),
) -> None:
    """Run the agent in the browser.

    There is no authentication: everybody who can reach the address can drive the
    agent in the working directory, so keep it on 127.0.0.1.
    """
    from coderagent.web.server import serve

    spec = list(config_spec)
    if model_name:
        spec.append(f"model.model_name={model_name}")
    serve(cwd=cwd, host=host, port=port, config_spec=spec, permission_mode=permission_mode or None)


@app.command("eval")
def eval_suite(
    suite: Path = typer.Argument(..., help="The directory of the suite"),
    model_name: str = typer.Option("", "-m", "--model", help="Model to use"),
    config_spec: list[str] = typer.Option([], "-c", "--config", help="Config file or key=value overrides"),
    only: list[str] = typer.Option([], "--only", help="Only the tasks with these ids"),
    tag: list[str] = typer.Option([], "--tag", help="Only the tasks with these tags"),
    output_format: str = typer.Option("text", "--format", help="text|json"),
    out: str = typer.Option("", "--out", help="The file to write the report to"),
    keep: bool = typer.Option(False, "--keep", help="Keep the working directories and the sessions"),
    label: str = typer.Option("", "--label", help="The name of this run"),
    run_dir: str = typer.Option("", "--run-dir", help="Where the working directories and the sessions live"),
    permission_mode: str = typer.Option("bypass", "--permission-mode", help="default|bypass"),
) -> None:
    """Run a suite of tasks and report what the agent did.

    Every task runs in its own working directory, with its own session. The
    sessions and the working directories live in a temporary directory, unless
    `--run-dir` or `--keep` says otherwise.
    """
    from coderagent.eval.report import Report, fingerprint, fingerprint_inputs
    from coderagent.eval.runner import run_suite
    from coderagent.eval.task import load_suite

    cwd = Path.cwd()
    config = load_config(config_spec, cwd=cwd)
    """The configuration of the user is read before the isolation, it holds the model."""
    if model_name:
        config.model.model_name = model_name
    tasks = [task for task in load_suite(suite) if _wanted(task, only, tag)]
    root = Path(run_dir) if run_dir else Path(tempfile.mkdtemp(prefix="coderagent-eval-"))
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["MSWEA_CODER_HOME"] = str(home)
    """From here on, every user level path of the agent is inside the run."""
    store = SessionStore(root=home / "sessions")
    started = time.time()
    results = run_suite(
        tasks,
        config,
        root=root / "work",
        store=store,
        permission_mode=permission_mode,
        user_home=home,
    )
    report = Report(
        label=label,
        suite=str(suite),
        model=config.model.model_name,
        fingerprint=fingerprint(config, config.model.model_name, permission_mode, tasks),
        config=fingerprint_inputs(config, config.model.model_name, permission_mode, tasks),
        started_at=started,
        duration_seconds=time.time() - started,
        tasks=results,
    )
    typer.echo(report.to_json() if output_format == "json" else report.to_text())
    if out:
        Path(out).write_text(report.to_json(), encoding="utf-8")
        typer.echo(f"Wrote {out}")
    if not keep and not run_dir:
        shutil.rmtree(root, ignore_errors=True)


def _wanted(task, only: list[str], tag: list[str]) -> bool:
    """Whether a task is part of the run."""
    if only and task.id not in only:
        return False
    return not tag or bool(set(tag) & set(task.tags))


@app.command()
def export(
    session: str = typer.Option("", "--session", help="The id of the session. The last one when empty."),
    output_format: str = typer.Option("json", "--format", help="json|otel"),
    out: str = typer.Option("", "--out", help="The file to write. The standard output when empty."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="The directory of the session"),
) -> None:
    """Write the trace of a session to a file."""
    import json

    from coderagent.core.telemetry import otel, trace

    store = SessionStore()
    session_id = session
    if not session_id:
        sessions = store.list(cwd)
        if not sessions:
            typer.echo("No sessions yet.")
            return
        session_id = sessions[0].id
    events = store.events(session_id)
    if output_format == "json":
        data = trace(events, store.rebuild(session_id))
    elif output_format == "otel":
        data = otel(events, store.rebuild(session_id))
    else:
        typer.echo(f"Unknown format '{output_format}'. Use json or otel.")
        return
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {out}")
        return
    typer.echo(text)
