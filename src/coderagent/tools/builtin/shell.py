"""Shell tool: `bash` plus the background task helpers `bash_output` and `bash_kill`."""

import os
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from coderagent.tools.base import ToolContext, ToolResult
from minisweagent.environments.local import LocalEnvironment

CHARS_PER_TOKEN = 3.5


class CodingEnvironment(LocalEnvironment):
    """Local environment without mini-swe-agent's `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` magic.

    A coding agent ends a turn when the model says so, not when a shell command prints a
    sentinel string.
    """

    def _check_finished(self, output: dict) -> None:
        return None


def trim_output(text: str, max_output_tokens: int) -> str:
    """Keep the head and the tail of long output, elide the middle."""
    limit = max(1, int(int(max_output_tokens) * CHARS_PER_TOKEN))
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    elided = len(text) - limit
    return f"{text[:head]}\n... [{elided} characters elided] ...\n{text[-tail:]}"


class BashTool:
    name = "bash"
    description = (
        "Run a shell command in the working directory. Use it for pipelines, builds and tests; "
        "use the dedicated file tools for reading and editing files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Defaults to the configured timeout."},
            "run_in_background": {"type": "boolean", "description": "Start the command and return a task id at once."},
        },
        "required": ["command"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = params.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult("Error: `command` is required and must be a non-empty string.", is_error=True)
        timeout = params.get("timeout")
        timeout = int(timeout) if isinstance(timeout, int) and timeout > 0 else ctx.config.bash_timeout
        if params.get("run_in_background"):
            return self._start_background(command, ctx)

        env = ctx.env if isinstance(ctx.env, CodingEnvironment) else CodingEnvironment(cwd=str(ctx.cwd))
        result = env.execute({"command": command}, cwd=str(ctx.cwd), timeout=timeout)
        output = str(result.get("output", ""))
        content = trim_output(output, ctx.config.max_output_tokens)
        returncode = result.get("returncode", 0)
        if result.get("exception_info"):
            content = f"{content}\n{result['exception_info']}".strip()
        elif returncode != 0:
            content = f"{content}\n[exit code {returncode}]".strip()
        return ToolResult(content, is_error=returncode != 0, metadata={"returncode": returncode})

    def _start_background(self, command: str, ctx: ToolContext) -> ToolResult:
        task_id = uuid.uuid4().hex[:8]
        directory = Path(tempfile.mkdtemp(prefix="coderagent-bg-"))
        log_path = directory / "output.log"
        handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(  # noqa: S602
            command,
            shell=True,
            text=True,
            cwd=str(ctx.cwd),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        ctx.background[task_id] = {"process": process, "handle": handle, "log": log_path, "command": command}
        return ToolResult(
            f"Started background task {task_id}: {command}\nUse `bash_output` with task_id={task_id} to check it.",
            metadata={"task_id": task_id},
        )


class BashOutputTool:
    name = "bash_output"
    description = "Show the output collected so far by a background bash task."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The id returned when the task was started."},
        },
        "required": ["task_id"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        task = ctx.background.get(str(params.get("task_id", "")))
        if task is None:
            return ToolResult(f"Error: unknown task id '{params.get('task_id')}'.", is_error=True)
        process = task["process"]
        output = task["log"].read_text(encoding="utf-8", errors="replace")
        status = "running" if process.poll() is None else f"exited with code {process.returncode}"
        content = trim_output(output, ctx.config.max_output_tokens)
        return ToolResult(f"{content}\n[status: {status}]", metadata={"status": status})


class BashKillTool:
    name = "bash_kill"
    description = "Kill a running background bash task."
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "The id returned when the task was started."},
        },
        "required": ["task_id"],
    }

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        task_id = str(params.get("task_id", ""))
        task = ctx.background.get(task_id)
        if task is None:
            return ToolResult(f"Error: unknown task id '{task_id}'.", is_error=True)
        process = task["process"]
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
        task["handle"].close()
        return ToolResult(f"Killed background task {task_id}.")


def wait_for_background(task: dict, timeout: float = 5.0) -> None:
    """Wait a bit for a background task to finish. Used by tests."""
    deadline = time.time() + timeout
    while time.time() < deadline and task["process"].poll() is None:
        time.sleep(0.05)
