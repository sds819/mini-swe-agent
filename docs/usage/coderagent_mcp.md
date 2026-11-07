# MCP servers

The coding agent can use the tools of an [MCP](https://modelcontextprotocol.io)
server. The MCP SDK is optional:

```bash
pip install "mini-swe-agent[mcp]"
```

## The configuration

```yaml
mcp:
  timeout: 30
  servers:
    - name: filesystem
      command: npx -y @modelcontextprotocol/server-filesystem /path/to/the/project
      env:
        LOG_LEVEL: info
```

The servers are read from the project file `.coderagent/config.yaml` and from
the user file `~/.coderagent/config.yaml`.

| Key | What it is |
|---|---|
| `name` | The name of the server. It is part of the name of its tools |
| `command` | The command that starts the server, over the standard input and output |
| `env` | The environment of the server |
| `enabled` | `false` skips the server |
| `timeout` | How long the agent waits for the server, in seconds |

Only the standard input and output transport works today. A server with a
`url` and no `command` is skipped: the http transport is not implemented yet.

The `env` of a server **replaces** its environment, it does not add to it. A
server that needs `PATH` has to be given one:

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx -y @modelcontextprotocol/server-filesystem .
      env:
        PATH: /usr/local/bin:/usr/bin:/bin
```

## What the tools look like

The tools of a server are named `mcp__<server>__<tool>`, so they never clash
with the built-in tools. The schema of the tool is the schema of the server.

```
mcp__filesystem__read_file
mcp__filesystem__list_directory
```

The tools of a server are external code, so they go through the permission
layer like every other tool: in the default mode the user has to approve them.
A rule that allows one for good looks like this:

```yaml
# .coderagent/rules.yaml
rules:
  - tool: "mcp__filesystem__read_file"
    pattern: "*"
    decision: allow
```

The name of the tool is the whole name, with the server in it. The `pattern`
is `*` or the same name: a glob does not work here.

## The servers and the session

The servers are started when the session starts, one thread each. A server
that does not start is skipped, the reason is in the log and `/mcp` shows it.
The other servers keep working.

```
/mcp
```

```
filesystem       connected
remote           not connected
broken           failed: MCPError: Connection closed
```

`not connected` is a server that was never started: it has no `command`, so
the http transport would be needed and it is not implemented yet. `failed` is
a server that was started and did not come up.

When a call breaks the connection, the agent reconnects and tries the call one
more time. When it fails again, the error goes back to the model.
