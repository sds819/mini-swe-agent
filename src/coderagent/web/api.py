"""The HTTP API of the web interface.

The pages are thin: everything they show comes from here. The events of a
session are pushed over SSE, everything else is a plain request and answer.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from coderagent.core.checkpoint import CheckpointStore
from coderagent.core.subagent import effective_turns, load_subagents
from coderagent.core.telemetry import collect
from coderagent.tools.permissions import ApprovalDecision, PermissionMode
from coderagent.ui.commands import COMMANDS, load_builtins
from coderagent.ui.widgets.diff_view import make_diff
from coderagent.web import config_api, files
from coderagent.web.events import normalize
from coderagent.web.sessions import SessionBusy, SessionRuntime

router = APIRouter(prefix="/api")

KEEP_ALIVE = 15
"""Seconds between two keep-alives of the event stream."""

STREAM_ENDS = ("turn_end", "command_end")
"""The items that close the event stream; the browser opens a new one."""


class MessageBody(BaseModel):
    text: str


class ApprovalBody(BaseModel):
    decision: str


def require_client(x_coder_client: str = Header(default="")) -> None:
    """The write requests need a header a browser on another site cannot send.

    The header makes the browser ask for a permission first, and no permission
    is granted, so a page somewhere else cannot drive the agent.
    """
    if x_coder_client != "1":
        raise HTTPException(status_code=403, detail="the X-Coder-Client header is missing")


def _runtime(request: Request, session_id: str) -> SessionRuntime:
    """The runtime of a session. A session of the log that has no runtime gets one."""
    registry = request.app.state.registry
    runtime = registry.get(session_id)
    if runtime is not None:
        return runtime
    session = registry.store.rebuild(session_id)
    if not session.created_at:
        raise HTTPException(status_code=404, detail=f"there is no session with the id {session_id}")
    return registry.create(session)


def _config(request: Request):
    """The configuration as it is now."""
    return request.app.state.config_of()


def _server_mode(request: Request) -> str:
    """The mode the server was started with, empty when it was not pinned."""
    return request.app.state.registry.permission_mode or ""


# -- the sessions --------------------------------------------------------


@router.get("/sessions")
def list_sessions(request: Request, cwd: str = "") -> dict[str, Any]:
    """The sessions of a directory, newest first."""
    directory = Path(cwd) if cwd else request.app.state.cwd
    sessions = request.app.state.registry.store.list(directory)
    return {
        "sessions": [
            {
                "id": session.id,
                "cwd": str(session.cwd),
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "turns": session.turn_count,
                "cost": session.total_cost,
                "state": session.state.value,
            }
            for session in sessions
        ]
    }


@router.post("/sessions", status_code=201)
def create_session(request: Request) -> dict[str, Any]:
    """Start a new session."""
    runtime = request.app.state.registry.create()
    return {"id": runtime.session.id, "cwd": str(runtime.cwd)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request, session_id)
    session = runtime.session
    return {
        "id": session.id,
        "cwd": str(session.cwd),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "turns": session.turn_count,
        "cost": session.total_cost,
        "state": session.state.value,
    }


@router.get("/sessions/{session_id}/events")
def replay(session_id: str, request: Request) -> dict[str, Any]:
    """The whole session, read from the event log."""
    runtime = _runtime(request, session_id)
    items: list[dict] = []
    for event in runtime.store.events(session_id):
        items.extend(normalize(event))
    return {"items": items}


@router.get("/sessions/{session_id}/items")
def items(session_id: str, request: Request, since: int = 0) -> dict[str, Any]:
    """The items of the session that the browser has not seen yet."""
    runtime = _runtime(request, session_id)
    return {"items": runtime.items(since)}


@router.get("/sessions/{session_id}/stream")
async def stream(session_id: str, request: Request, since: int = 0) -> StreamingResponse:
    """The events of the session, as they happen."""
    runtime = _runtime(request, session_id)
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    runtime.attach(loop, queue, since)

    async def events():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=KEEP_ALIVE)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("kind") in STREAM_ENDS:
                    break
        finally:
            runtime.detach(queue)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/status")
def status(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request, session_id)
    return runtime.status()


@router.get("/sessions/{session_id}/metrics")
def metrics(session_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request, session_id)
    return collect(runtime.store.events(session_id)).to_dict()


@router.get("/sessions/{session_id}/changes")
def changes(session_id: str, request: Request) -> dict[str, Any]:
    """The files this session changed, with the diff of the change."""
    runtime = _runtime(request, session_id)
    config = _config(request)
    store = CheckpointStore(keep=config.checkpoint.keep)
    seen: dict[str, str] = {}
    for checkpoint in store.all(session_id):
        for name, before in checkpoint.payload.items():
            seen.setdefault(name, before or "")
    result = []
    for name, before in seen.items():
        path = runtime.cwd / name
        after = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        result.append({"path": name, "diff": make_diff(before, after, name)})
    return {"changes": result}


@router.post("/sessions/{session_id}/resume")
def resume(session_id: str, request: Request) -> dict[str, Any]:
    """Continue a session of the log."""
    runtime = _runtime(request, session_id)
    session = runtime.resume()
    return {"id": session.id}


@router.post("/sessions/{session_id}/fork")
def fork(session_id: str, request: Request) -> dict[str, Any]:
    """Copy a session into a new one."""
    runtime = _runtime(request, session_id)
    forked = runtime.store.fork(session_id)
    new_runtime = request.app.state.registry.create(forked)
    return {"id": new_runtime.session.id, "forked_from": session_id}


@router.post("/sessions/{session_id}/messages", status_code=202)
def send_message(session_id: str, body: MessageBody, request: Request, _: None = Depends(require_client)) -> dict:
    """Send a message, or run a slash command."""
    runtime = _runtime(request, session_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="the message is empty")
    try:
        runtime.submit(text)
    except SessionBusy as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {"accepted": True, "session_id": runtime.session.id}


@router.post("/sessions/{session_id}/interrupt")
def interrupt(session_id: str, request: Request, _: None = Depends(require_client)) -> dict[str, Any]:
    """Stop the turn that is running."""
    runtime = _runtime(request, session_id)
    runtime.interrupt()
    return {"ok": True}


@router.post("/sessions/{session_id}/mode")
def set_mode(session_id: str, body: dict, request: Request, _: None = Depends(require_client)) -> dict:
    """Change the permission mode of a session while it runs."""
    runtime = _runtime(request, session_id)
    value = str(body.get("mode") or "")
    try:
        mode = PermissionMode(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown permission mode '{value}'")
    runtime.set_mode(mode)
    return {"ok": True, "mode": mode.value}


# -- the approvals --------------------------------------------------------


@router.post("/approvals/{approval_id}")
def answer_approval(
    approval_id: str, body: ApprovalBody, request: Request, _: None = Depends(require_client)
) -> dict[str, Any]:
    """Let a tool run, or not."""
    decision = {"allow": ApprovalDecision.ALLOW, "deny": ApprovalDecision.DENY, "always": ApprovalDecision.ALWAYS}
    if body.decision not in decision:
        raise HTTPException(status_code=400, detail="the decision must be allow, deny or always")
    for runtime in request.app.state.registry.runtimes():
        if runtime.approver.answer(approval_id, decision[body.decision]):
            return {"ok": True, "decision": body.decision}
    raise HTTPException(status_code=404, detail=f"no approval is waiting for the id {approval_id}")


# -- the commands ---------------------------------------------------------


@router.get("/commands")
def commands() -> dict[str, Any]:
    """The slash commands the user can type."""
    load_builtins()
    return {
        "commands": [
            {"name": command.name, "description": command.description, "aliases": command.aliases}
            for command in COMMANDS
        ]
    }


@router.get("/agents")
def agents(request: Request) -> dict[str, Any]:
    """The sub agents, with the turns they may really make.

    The turns of a sub agent are its own, but the ceiling of the configuration
    holds them down. The number here is the one that counts.
    """
    ceiling = _config(request).agent.subagent_max_turns
    specs = load_subagents(request.app.state.cwd)
    return {
        "ceiling": ceiling,
        "agents": [
            {
                "name": spec.name,
                "description": spec.description,
                "tools": spec.tools,
                "purpose": spec.model_purpose,
                "turns": effective_turns(spec, ceiling),
            }
            for spec in specs.values()
        ],
    }


# -- the configuration -----------------------------------------------------


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    """The model configuration, with the layer every setting comes from."""
    cwd = request.app.state.cwd
    return {
        "model": config_api.model_view(cwd),
        "permissions": config_api.permissions_view(cwd, server_mode=_server_mode(request)),
        "sources": config_api.sources(cwd),
        "layers": config_api.layers_preview(cwd),
        "user_config_path": str(config_api.user_config_path()),
    }


@router.put("/config/model")
def put_config(body: dict, request: Request, _: None = Depends(require_client)) -> dict[str, Any]:
    """Write the model settings to the user level configuration file."""
    path = config_api.write_user_model(body)
    return {"ok": True, "path": str(path), "model": config_api.model_view(request.app.state.cwd)}


@router.get("/config/model/key")
def get_config_key(request: Request, _: None = Depends(require_client)) -> dict[str, Any]:
    """The key of the model, so that it can be read in the settings page."""
    return {"api_key": config_api.effective_api_key(request.app.state.cwd)}


@router.put("/config/permissions")
def put_permissions(body: dict, request: Request, _: None = Depends(require_client)) -> dict[str, Any]:
    """Write the permission settings to the user level configuration file."""
    try:
        path = config_api.write_user_permissions(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {
        "ok": True,
        "path": str(path),
        "permissions": config_api.permissions_view(request.app.state.cwd, server_mode=_server_mode(request)),
    }


@router.post("/config/model/test")
def check_model(body: dict, request: Request, _: None = Depends(require_client)) -> dict[str, Any]:
    """Try the model out, to see whether the settings work."""
    return config_api.test_connection(config_api.effective_model(request.app.state.cwd, body))


# -- the files -------------------------------------------------------------


@router.get("/files")
def list_files(request: Request, path: str = "", depth: int = Query(1, ge=-1, le=10)) -> dict[str, Any]:
    """The entries of a directory of the working directory."""
    cwd = request.app.state.cwd
    policy = files.policy_for(_config(request), cwd)
    try:
        entries = files.directory(cwd, path, depth, policy)
    except files.OutsideBounds as error:
        raise HTTPException(status_code=403, detail=str(error))
    except (NotADirectoryError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"path": path, "entries": entries}


@router.get("/file")
def read_file(path: str, request: Request) -> dict[str, Any]:
    """The content of a file of the working directory."""
    cwd = request.app.state.cwd
    policy = files.policy_for(_config(request), cwd)
    try:
        return files.read(cwd, path, policy, _config(request))
    except files.OutsideBounds as error:
        raise HTTPException(status_code=403, detail=str(error))
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/diff")
def diff(path: str, request: Request) -> dict[str, Any]:
    """The changes of the working tree for a path."""
    cwd = request.app.state.cwd
    policy = files.policy_for(_config(request), cwd)
    try:
        return {"path": path, "diff": files.diff(cwd, path, policy)}
    except files.OutsideBounds as error:
        raise HTTPException(status_code=403, detail=str(error))
    except OSError as error:
        raise HTTPException(status_code=400, detail=str(error))
