"""MCP: the tools of an MCP server, used like the built-in ones.

The MCP SDK is asynchronous, the agent is not. Every server therefore gets a
thread with its own event loop; the tools call into it and wait for the answer.
"""

import asyncio
import json
import logging
import shlex
import threading
from contextlib import AsyncExitStack
from typing import Any

from coderagent.config.schema import MCPServerConfig
from coderagent.core.events import EventBus
from coderagent.tools.base import ToolContext, ToolResult

logger = logging.getLogger("coderagent.mcp")


def tool_name(server: str, tool: str) -> str:
    """The name a tool of a server gets: `mcp__<server>__<tool>`."""
    return f"mcp__{server}__{tool}"


class MCPTool:
    """A tool of an MCP server, seen from the agent."""

    def __init__(
        self, client: "MCPClient", name: str, remote: str, description: str, parameters: dict[str, Any]
    ) -> None:
        self.client = client
        self.name = name
        self.remote = remote
        """The name the server knows the tool by."""
        self.description = description
        self.parameters = parameters

    def run(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return self.client.call(self.remote, params)


class MCPClient:
    """One MCP server: the connection, its tools and the calls to them."""

    def __init__(self, config: MCPServerConfig, bus: EventBus | None = None, timeout: int = 30) -> None:
        self.config = config
        self.bus = bus
        self.timeout = timeout
        self._error = ""
        """Why the server is not available, when it is not."""
        self._session = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._tools: list[MCPTool] = []

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools

    @property
    def error(self) -> str:
        """Why the server is not available, when it is not."""
        return self._error

    def start(self) -> list[MCPTool]:
        """Connect to the server and return its tools. Never raises."""
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"mcp-{self.config.name}")
        self._thread.start()
        self._ready.wait(self.timeout)
        if self._error:
            logger.warning("MCP server '%s' is not available: %s", self.config.name, self._error)
        return self._tools

    def stop(self) -> None:
        """Close the connection to the server."""
        self._stop.set()
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:
            pass

    def call(self, name: str, arguments: dict) -> ToolResult:
        """Call a tool of the server and turn its answer into a tool result.

        A broken connection is tried once more with a new one.
        """
        if self._session is None:
            return ToolResult(content=f"Error: the MCP server '{self.config.name}' is not connected.", is_error=True)
        try:
            result = self._call_remote(name, arguments)
        except Exception as e:
            logger.warning("The MCP server '%s' broke: %s", self.config.name, e)
            self._restart()
            try:
                result = self._call_remote(name, arguments)
            except Exception as retry_error:
                return ToolResult(
                    content=f"Error: the MCP tool '{name}' failed: {type(retry_error).__name__}: {retry_error}",
                    is_error=True,
                )
        return ToolResult(content=_content_text(result), is_error=bool(getattr(result, "isError", False)))

    def _call_remote(self, name: str, arguments: dict):
        return asyncio.run_coroutine_threadsafe(self._call(name, arguments), self._loop).result(self.timeout)

    def _restart(self) -> None:
        """Start over with a new connection."""
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=self.timeout)
        self._thread = None
        self._session = None
        self._tools = []
        self._error = ""
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.start()

    async def _call(self, name: str, arguments: dict):
        return await self._session.call_tool(name, arguments)

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:
            self._error = _describe(e)
            logger.warning("MCP server '%s' failed: %s", self.config.name, self._error)
        finally:
            self._ready.set()

    async def _main(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._loop = asyncio.get_running_loop()
        command, args = _split_command(self.config.command)
        params = StdioServerParameters(command=command, args=args, env=self.config.env or None)
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(stdio_client(params))
            self._session = await stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            self._tools = self._make_tools(await self._session.list_tools())
            self._ready.set()
            while not self._stop.is_set():
                await asyncio.sleep(0.05)

    def _make_tools(self, listed) -> list[MCPTool]:
        tools = []
        for tool in listed.tools:
            schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
            schema = schema or {"type": "object", "properties": {}}
            tools.append(
                MCPTool(
                    self,
                    tool_name(self.config.name, tool.name),
                    tool.name,
                    tool.description or f"The tool '{tool.name}' of the MCP server '{self.config.name}'.",
                    schema,
                )
            )
        return tools


class MCPManager:
    """All the servers of the configuration."""

    def __init__(self, config, bus: EventBus | None = None) -> None:
        self.config = config
        self.bus = bus
        self.clients: list[MCPClient] = []

    def start(self) -> list[MCPTool]:
        """Connect to every server and return the tools that work."""
        tools: list[MCPTool] = []
        for server in self.config.servers:
            if not server.enabled or not server.command:
                continue
            client = MCPClient(server, self.bus, self.config.timeout)
            self.clients.append(client)
            tools.extend(client.start())
        return tools

    def status(self) -> dict[str, str]:
        """The state of every server, by name."""
        return {
            client.config.name: f"failed: {client.error}" if client.error else "connected" for client in self.clients
        }

    def stop(self) -> None:
        for client in self.clients:
            client.stop()


def _describe(error: BaseException) -> str:
    """The message of an error, with the errors of a group unwrapped."""
    if hasattr(error, "exceptions"):
        return ", ".join(_describe(sub) for sub in error.exceptions)
    return f"{type(error).__name__}: {error}"


def _split_command(command: str) -> tuple[str, list[str]]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("the MCP server has no command")
    return parts[0], parts[1:]


def _content_text(result) -> str:
    """The content of an MCP answer, as text."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
            continue
        data = getattr(item, "data", None)
        if data is not None:
            parts.append(f"[{getattr(item, 'mimeType', 'binary')}] {len(data)} bytes")
            continue
        parts.append(json.dumps(item, default=str))
    return "\n".join(parts)
