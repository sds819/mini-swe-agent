# The web interface

`coder web` runs the same agent in the browser. The chat page is the terminal
interface with a window around it, and the settings page writes the model
configuration for you — which is the part that is tedious in a text editor.

> 中文版：[网页版](coderagent_web_zh.md)

```bash
pip install -e ".[web]"      # fastapi, uvicorn and jinja2
cd my-project
coder web
```

The server prints the address it listens on and waits:

```
coder web: http://127.0.0.1:8765
```

Open that address in a browser.

## The command line

| Option | What it does |
|---|---|
| `--cwd` | The directory the agent works in. Everything the browser shows is inside it. |
| `--host` | The address to listen on. `127.0.0.1` by default. |
| `--port` | The port. `8765` by default. |
| `--model`, `-m` | The model of this run |
| `--config`, `-c` | A configuration file, or `key=value` overrides |
| `--permission-mode` | `default`, `acceptEdits`, `plan`, `bypass` or `readonly` |

## The pages

### The chat page (`/`)

Three columns:

- **Left**: the sessions of the directory and the files of the working
  directory. `New session` starts one; clicking a session opens it.
- **Middle**: the conversation. Messages are bubbles, tool calls are cards with
  the output and the diff of the change, approvals are cards with three
  buttons. The box under the conversation takes a message or a slash command
  (`/help`, `/clear`, `/cost`, … — the same commands as the terminal
  interface). `Interrupt` stops the turn that is running.

  The page itself does not scroll: every column has its own scrollbar. The
  conversation follows the newest output, unless you scroll up to read
  something. The turns before the current one are folded into a block at the
  top — click it to look at them.
- **Right**: the status bar of the session (model, context size, cost, mode),
  the files the session changed with their diff, and the file you are looking
  at.

Everything the agent does arrives over a server-sent event stream, so the
output appears while it happens. Reconnecting to the page picks up where it
left off.

The pieces of a streamed answer are only for the moment: they are pushed to the
browser while they arrive but not kept, so a long answer cannot push the
history of the session out of the buffer. A browser that comes late reads the
whole answer as one message.

At the end of a turn the session is settled in the memory (see
[The memory](coderagent_memory.md)), which shows up as a thin separator with
what it cost.

### The settings page (`/settings`)

The model configuration, in a form:

| Field | What it is |
|---|---|
| Model name | `model.model_name`, e.g. `deepseek/deepseek-flash` |
| API base | `model.model_kwargs.api_base` — the address of the provider |
| API key | `model.model_kwargs.api_key`. Write-only: it is never sent back to the browser |
| Retries | `model.max_retries` |
| Cache control | `model.set_cache_control` |
| Routing | `model.routing` |
| Routing rules | `model.routing_rules` |
| Extra parameters | Everything else of `model.model_kwargs` |

Under every field is the layer it comes from: `defaults`, `project`, `user` or
`env`. The table at the bottom shows every layer, with the secrets taken out.

`Test connection` sends one cheap call to the model with the settings of the
form, so you can see whether the key and the address work before you save.

**What is written where**: only the user level file, `~/.coderagent/config.yaml`
(or `$MSWEA_CODER_HOME/config.yaml`). The project level file
(`.coderagent/config.yaml`) is **never** written — it is in the repository.
The sections the page does not know about are kept as they are; the comments
in the file are lost.

**A key in the environment is not in the page.** The page reads the
configuration files, so a provider key that comes from the environment
(`DEEPSEEK_API_KEY` and the like) is not shown and `api_key_set` stays false.
That is the normal case; the page is for the keys that live in the
configuration.

**When it takes effect**: the server keeps the configuration it started with.
A **new** session reads the files again, so the new settings apply from the
next session on. The session you are in keeps the model it has; use `/model
<name>` to switch it right away.

## Permissions

The permissions are in two places, and they do different things.

| Where | What it changes | When it takes effect |
|---|---|---|
| The settings page (`/settings`) | The `permissions:` section of the user level configuration file | The **next** session |
| The chat page (`/`) | The mode of the session that is running | **Right away** |

### The modes

| Mode | What it means |
|---|---|
| `default` | Every tool that changes something asks for approval |
| `acceptEdits` | The writes go through, everything else asks |
| `plan` | Read only: the agent looks around and writes down the plan |
| `readonly` | Read only: the agent looks around and answers |
| `bypass` | Nothing is asked: every tool call is allowed. For unattended runs |

`plan` and `readonly` refuse every tool that changes something, `bash`
included, and the model is told about it, so it answers with what it found
instead of changing anything.

### The settings page

The form has the mode, the denied paths and the extra directories, and it is
written to the same user level file as the model: `~/.coderagent/config.yaml`
(or `$MSWEA_CODER_HOME/config.yaml`). The project level file is never
written, and the rules of `permissions.rules` are left alone — those are the
business of the `Always allow` button of the approvals.

Like the model, it takes effect for the **new** sessions: a session that is
running keeps the mode it has.

### The chat page

The inspector has a mode box at the top. Changing it switches the mode of the
session that is running, without restarting anything: the policy is changed
in place, so the next tool call sees it, and the model is told about it the
next time the context is put together. This is what makes an unattended run
easy — put the session on `bypass` before the test run, back to `default`
afterwards.

### The mode the server was started with

`coder web --permission-mode bypass` pins the mode: it wins over the files,
because the policy is built with `permission_mode or config.permissions.mode`.
The settings page says so when the server was started with one, instead of
letting you believe that a change in the file took effect.

The pin is the mode the sessions **start** with, not a lock: the chat page
can still switch the mode of a session, because that is a decision you take
in front of the session, not a setting of the file.

## The API

Everything the pages do is a plain HTTP call, so you can drive the agent from
a script. The interactive documentation is at `/api/docs`.

The write endpoints (messages, approvals, interrupt, configuration) ask for the
header `X-Coder-Client: 1`. A browser on another site cannot send that header
without asking the server first, and the server does not grant it, so a page
somewhere else cannot drive your agent. `curl` is not affected.

| Method | Path | What it does |
|---|---|---|
| GET | `/api/sessions` | The sessions of the directory |
| POST | `/api/sessions` | A new session |
| GET | `/api/sessions/{id}` | One session |
| GET | `/api/sessions/{id}/events` | The whole session, read from the log |
| GET | `/api/sessions/{id}/items?since=` | The items the browser has not seen yet |
| GET | `/api/sessions/{id}/stream?since=` | The event stream (SSE) |
| GET | `/api/sessions/{id}/status` | The fields of the status bar |
| GET | `/api/sessions/{id}/metrics` | What the session cost |
| GET | `/api/sessions/{id}/changes` | The files the session changed, with their diff |
| POST | `/api/sessions/{id}/resume` | Continue a session of the log |
| POST | `/api/sessions/{id}/fork` | Copy a session |
| POST | `/api/sessions/{id}/messages` | Send a message, or run a slash command |
| POST | `/api/sessions/{id}/interrupt` | Stop the turn that is running |
| POST | `/api/sessions/{id}/mode` | Change the permission mode of the session |
| POST | `/api/approvals/{id}` | Allow, deny or always allow a tool |
| GET | `/api/commands` | The slash commands |
| GET | `/api/config` | The model configuration, with the layer of every field |
| PUT | `/api/config/model` | Write the model settings to the user file |
| PUT | `/api/config/permissions` | Write the permission settings to the user file |
| POST | `/api/config/model/test` | Try the settings out |
| GET | `/api/files?path=&depth=` | The entries of a directory |
| GET | `/api/file?path=` | The content of a file |
| GET | `/api/diff?path=` | The changes of the working tree |

A turn that is already running makes the next message fail with `409`. An
approval that nobody is waiting for is a `404`. A path outside the working
directory is a `403`. A permission mode that does not exist is a `400`.

## Approvals

A tool that needs permission waits for you. The card in the conversation has
three buttons:

- **Allow** — this call runs.
- **Deny** — the call does not run and the model is told that you said no, so
  it can do something else.
- **Always allow** — this call runs **and a rule is written to
  `~/.coderagent/rules.yaml`**, so the same tool is allowed from now on. The
  button says so.

If nobody answers, the call is denied (`ui.approval_timeout` seconds, five
minutes by default). A tool that is denied never runs.

## The security model

Read this before you put it on a network.

- **There is no authentication.** Everybody who can reach the port can drive
  the agent, and the agent can run shell commands in the working directory.
  This is a tool for one person on one machine, the same trust you give the
  `coder` command line.
- **It listens on `127.0.0.1` by default.** `--host 0.0.0.0` prints a warning
  and serves to everybody who can reach the machine.
- **The browser cannot be tricked into it.** The write endpoints need a header
  that a cross-site request cannot send without a permission the server does
  not give.
- **The browser cannot look outside the working directory.** Every path is
  resolved and checked against the working directory and the directories in
  `permissions.include_dirs`. The rules of the user cannot widen that.
- **The API key never leaves the server.** The settings page only ever gets
  `api_key_set` and the last four characters; the preview of the layers has
  every secret replaced by `***`.
- **The api key is written to the user file only**, never to the project file
  that goes into the repository.

## The differences from the terminal interface

| | Terminal | Browser |
|---|---|---|
| Streaming | Yes | Yes, over SSE |
| Approvals | Yes | Yes, with the same three answers |
| Slash commands | Yes | Yes, the same ones |
| The model configuration | A text file | A form, plus a preview of the layers |
| The files of the project | The tools of the agent | A tree on the left |
| The cost | `/cost` | The status bar, and `/cost` |

The core is the same: the same sessions, the same event log, the same tools,
the same permissions. A session started in the browser can be continued in the
terminal with `coder --resume <id>`, and the other way round.

What the browser does not have yet: the terminal interface can pick the answer
of an approval with the arrow keys, and it can fold a long output away. The
browser shows everything.

## Known gaps

- The stream ends when the turn ends. A turn that says nothing for a long
  time keeps the connection open, but the browser has to reconnect after every
  turn.
- The changed files come from the checkpoints of the session. A file that was
  changed without a checkpoint is not in the list.
- Each session gets its own MCP server threads. The servers are only started
  when a session runs its first turn, but a lot of sessions means a lot of
  threads.

If the port is taken, the server says so and stops; start it on another one
with `--port`.
