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
      command: npx -y @modelcontextprotocol/server-filesystem ${workspace}
      env:
        LOG_LEVEL: info
    - name: remote
      url: https://example.com/mcp
      headers:
        Authorization: Bearer ${TOKEN}
```

The servers are read from the project file `.coderagent/config.yaml` and from
the user file `~/.coderagent/config.yaml`.

- `command` starts the server over the standard input and output. This is the
  transport that works today.
- `url` and `headers` are for the http transport. The interface is there, the
  transport is not implemented yet.
- `enabled: false` skips a server.

## What the tools look like

The tools of a server are named `mcp__<server>__<tool>`, so they never clash
with the built-in tools. The schema of the tool is the schema of the server.

The tools of a server are external code, so they go through the permission
layer like every other tool: in the default mode the user has to approve them.
A rule that allows them for good looks like this:

```json
{"tool": "mcp__filesystem__read_file", "pattern": "*", "decision": "allow"}
```

## What happens when a server fails

The servers are started when the session starts. A server that does not start
is skipped, the reason is in the log and `/mcp` shows it. The other servers keep
working.
