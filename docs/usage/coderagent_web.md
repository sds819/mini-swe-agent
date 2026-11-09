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
| Model name | `model.model_name`, e.g. `deepseek/deepseek-flash`. The provider in front of the name says who is called: `openai/MiniMax-M2.7` for a third party endpoint, `deepseek/deepseek-flash` for DeepSeek |
| Litellm config file | `model.litellm_config` — the file with the aliases of the models |
| API base | `model.model_kwargs.api_base` — the address of the provider |
| API key | `model.model_kwargs.api_key`. A click shows it, a second click hides it again |
| Retries | `model.max_retries` |
| Cache control | `model.set_cache_control` |
| Routing | `model.routing` |
| Routing rules | `model.routing_rules` |
| Extra parameters | Everything else of `model.model_kwargs` |

Under every field is the layer it comes from: `defaults`, `project`, `user` or
`env`. The table at the bottom shows every layer, with the secrets taken out.

The **Example** block under the fields shows how a third party endpoint is
written: the model name is then an alias of the model list of a litellm config
file, and the key of the endpoint stays in that file instead of the settings of
the agent.

`Test connection` sends one cheap call to the model with the settings of the
form, so you can see whether the key and the address work before you save. It
reports four things:

| What | What it tells you |
|---|---|
| The model | The model the call goes to, and the alias it comes from |
| The API base and the key | The address and whether a key is set (only its tail) |
| The aliases file | Whether the file exists, whether it parses, and which aliases it has |
| The tools | Whether the model calls the tools — without that the agent cannot work |

**Test a model.** A second panel tries a model out without saving anything:
the endpoint, the key and the name of the model, and a `Test connection`
button. It is the shape a provider hands them out in.

| Field | What it is |
|---|---|
| Endpoint | The address of the provider. The full address of the chat completions (`https://api.example.com/v1/chat/completions`) is fine — the part behind `/v1` is cut off, because litellm adds it itself |
| API Key | The key of that endpoint. A click shows the key of the settings above, a second click hides it again |
| Model Name | The name of the model. The provider in front of the name says who is called: `openai/MiniMax-M2.7`. Without one, the provider `openai` is added, because the endpoint is an OpenAI compatible one |

An empty endpoint or an empty key means the one of the settings above. The
result is the same four lines as the test of the form.

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

**The key of the field.** The field of the key shows `set (********1234)` while
the key itself stays hidden. A click on the field asks the server for the key
and shows it; a second click hides it again. The key of the aliases file counts
too: if the key lives in the litellm config file, that is the one that is shown.
An empty field keeps the key that is set — the key is only sent when there is
something in the field.

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

## The language of the pages

The pages are in Chinese for a visitor from a Chinese region (China, Hong
Kong, Macau, Taiwan) and in English everywhere else. The region of the visitor
is what decides.

| Where the region comes from | How |
|---|---|
| The proxy in front of the server | The header it sets: `CF-IPCountry`, `X-AppEngine-Country`, `X-Vercel-IP-Country`, `X-Country-Code` |
| The geoip database | `GeoLite2-Country.mmdb` in `~/.coderagent/` (or the path in `CODERAGENT_GEOIP_DB`). It needs the `geoip2` package, which is not a dependency of the agent |
| The browser | The `accept-language` header, when the region is not known |

The visitor always wins: the box in the top bar switches the language and
remembers it in a cookie, and `?lang=zh` (or `?lang=en`) works on every page.

The switch does not leave the page: the page of that language is fetched and
put in place, so the whole page — the text of the templates and the text the
browser writes — changes language right away. The choice is kept in the
browser as well as in the cookie, so a refresh does not change it back.

What decides, in this order:

1. **The choice of the visitor** — the language in the box of the top bar (kept
   in a cookie) or `?lang=zh` on the address. This one is the highest: a
   visitor from a Chinese region who picks English gets the English pages.
2. **The region of the address** — a visitor from a Chinese region gets the
   Chinese pages, everybody else the English ones.
3. **The language the browser asks for** — only when the region is not known,
   which is the case when the server is reached directly, without a proxy in
   front of it.

### Adding a language

A language is added in three places:

1. `src/coderagent/web/templates/<code>/` — a copy of the directory of
   `en/` with the text translated. `base.html`, `chat.html`, `settings.html`
   and `macros.html` are the files.
2. `src/coderagent/web/i18n.py` — an entry in `LANGUAGES` (the code, the name
   of the language in that language, the name in English) and the strings of
   the browser in `STRINGS`.
3. `src/coderagent/web/i18n.py` — the regions of that language in
   `REGION_LANGUAGES`, so that the visitors of those regions get it without
   asking.

A language whose templates are missing is not offered: the box in the top bar
only lists the languages that can be served, and a language that is not
served falls back to English.

The strings of `STRINGS` are the ones the browser shows while it works (the
text of the buttons, the labels of the status bar). The text of the pages
themselves is in the templates.

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
| GET | `/api/config/model/key` | The key of the model, in clear text |
| GET | `/lang/{language}` | The language of the pages, remembered in a cookie |
| GET | `/api/i18n/{language}` | The strings of a language, for a browser that switches without a reload |
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
- **The key is only shown on request.** The settings page only gets
  `api_key_set` and the last four characters; the preview of the layers has
  every secret replaced by `***`. The key itself is sent when you click the
  field of the key, and that request needs the header of the client, so a page
  somewhere else cannot ask for it.
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
