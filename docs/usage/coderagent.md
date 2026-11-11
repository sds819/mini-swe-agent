# The coding agent

`coder` is an interactive agent that works in a code repository. It reads the
code, writes the code, runs the commands and tells you what it changed. It
lives in the same package as `mini`, next to it:

```bash
pip install -e .            # the agent
pip install -e ".[mcp]"     # with the MCP servers
pip install -e ".[full]"    # with everything: swerex, modal, contree
```

The command is `coder`.

## The first session

```bash
cd my-project
coder
```

The interface opens in the directory of the project. Type what you want, for
example `fix the failing test in tests/test_parser.py`, and the agent works
through it. The status bar at the top shows the model, the size of the context,
what the session has cost so far, the sandbox and the permission mode.

Without a terminal there is one turn and then the answer:

```bash
coder --task "fix the failing test in tests/test_parser.py"
```

The keys of the model come from the environment or from the `.env` file of
mini-swe-agent (see [Global configuration](../advanced/global_configuration.md)).
The name of the model is `model.model_name` in the configuration, or
`MSWEA_MODEL_NAME` in the environment.

## The command line

| Option | What it does |
|---|---|
| `--task`, `-t` | The task. Without it, the interface opens. |
| `--model`, `-m` | The model of this run |
| `--config`, `-c` | A configuration file, or `key=value` overrides |
| `--cwd` | The directory of the session |
| `--permission-mode` | `default`, `acceptEdits`, `plan`, `bypass` or `readonly` |
| `--output-format` | `text` (the default) or `json` |
| `--resume <id>` | Continue the session with this id |
| `--continue` | Continue the last session of this directory |
| `--fork <id>` | Copy the session with this id and continue in the copy |
| `--list` | The sessions of this directory |
| `--tui` | Start the interface, even when there is no terminal |

`--print` is accepted and has no effect.

The overrides of `-c` are `key=value` pairs, the key is a path in the
configuration:

```bash
coder -c model.model_name=deepseek/deepseek-flash -c permissions.mode=plan
```

### The output

The text output is the conversation and one line about the turn:

```
[stop_reason=end_turn cost=0.0016 session_cost=0.0019 session=20261106-a1b2c3]
```

`cost` is what this turn cost, `session_cost` is what the whole session cost.
The json output has the same numbers in fields:

```bash
coder --task "..." --output-format json
```

```json
{
  "session_id": "20261106-a1b2c3",
  "messages": [{"role": "assistant", "content": "The test needed a fixture."}],
  "cost": 0.0016,
  "session_cost": 0.0019,
  "stop_reason": "end_turn",
  "error": ""
}
```

`stop_reason` is `end_turn`, `max_turns`, `cost_exceeded`, `token_limit`, `verify_failed`,
`interrupted` or `error`. `error` is empty unless the turn failed.

### The trace of a session

```bash
coder export --session 20261106-a1b2c3 --format json --out trace.json
coder export --session 20261106-a1b2c3 --format otel --out trace.otlp
```

The trace is the event log of the session with the metrics of the session. See
[Trace export](coderagent_export.md).

## The terminal interface

| Key | What it does |
|---|---|
| `ctrl+c` | Stop the turn that is running. A second time leaves. |
| `ctrl+q` | Leave. The session is settled in the memory first. |

When the agent wants to run a tool that needs approval, the interface asks.
`y` allows it once, `n` refuses it, `a` allows it for the rest of the
session. The refusal goes back to the model, which then does something else.

The answers are listed one per line, each in a numbered box:

```
1 [*] y allow
2 [-] n deny
3 [-] a always allow
```

The box of the picked answer is starred in red, the others have a grey dash.
The arrow keys (`←`/`→` or `↑`/`↓`) move the pick, the numbers jump to an
answer, and `enter` confirms it.

## The web interface

The same agent, in the browser:

```bash
pip install -e ".[web]"
coder web
```

The chat page is the terminal interface with a window around it, and the
settings page writes the model configuration — including the API key — for
you. The permissions are there too: the settings page writes the mode that the
new sessions get, the chat page switches the mode of the session that is
running. The pages, the API and the security model are in
[The web interface](coderagent_web.md).

## The configuration

Four layers, the later ones win:

1. the built-in defaults,
2. `.coderagent/config.yaml` of the project,
3. `~/.coderagent/config.yaml` of the user,
4. the `-c key=value` overrides of the command line.

A full example:

```yaml
model:
  model_name: deepseek/deepseek-flash
  model_kwargs:
    temperature: 0.0
  litellm_config: ~/.coderagent/litellm_config.yaml
  routing:
    cheap: deepseek/deepseek-flash
    summarize: deepseek/deepseek-flash

agent:
  max_turns: 50
  cost_limit: 5.0

tools:
  enabled: [read, write, edit, glob, grep, ls, bash, todo_write]
  disabled: [bash_output]
  bash_timeout: 120

permissions:
  mode: default
  deny_paths: ["*.env", "secrets/**"]
  include_dirs: ["../shared-library"]
  rules:
    - tool: bash
      pattern: "git push"
      decision: deny
      reason: pushing is not my job

context:
  context_window: 64000
  compact_threshold: 0.8
  summarize_model: deepseek/deepseek-flash

memory:
  enabled: true

sandbox:
  type: local
```

### The model

`model.model_name` is the model of the agent. `model.model_kwargs` goes to the
provider as it is. `model.routing` maps a purpose to a model:

| Purpose | What it is for |
|---|---|
| `main` | The agent itself |
| `cheap` | The small jobs: the sub agents that look around |
| `summarize` | The summary of a compacted context |
| `reflect` | What the session writes into the memory |
| `strong` | A stronger model, when the routing rules ask for it |

`model.routing_rules` are conditions on the state of the session:

```yaml
model:
  routing:
    strong: anthropic/claude-sonnet-4-5
  routing_rules:
    - when: "tokens > 50000"
      purpose: strong
```

The rules compare numbers only, they are parsed and not evaluated, so a
configuration file cannot run code. The interface says in the event stream when
the model changes and why. See [Model routing](coderagent_routing.md).

#### Other providers

The model goes through [litellm](https://github.com/BerriAI/litellm), so every
model litellm knows works. The name carries the provider in front of it, and
the key of the provider comes from the environment:

| Model name | Provider | Environment variable |
|---|---|---|
| `anthropic/claude-sonnet-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `openai/gpt-4o` | OpenAI | `OPENAI_API_KEY` |
| `deepseek/deepseek-flash` | DeepSeek | `DEEPSEEK_API_KEY` |
| `dashscope/qwen3-coder-plus` | Alibaba (DashScope) | `DASHSCOPE_API_KEY` |
| `moonshot/kimi-k2.5` | Moonshot | `MOONSHOT_API_KEY` |
| `minimax/minimax-m2` | MiniMax | `MINIMAX_API_KEY` (and `MINIMAX_API_BASE`) |
| `openrouter/qwen/qwen3-coder` | OpenRouter | `OPENROUTER_API_KEY` |

```bash
export DASHSCOPE_API_KEY=sk-...
coder -m dashscope/qwen3-coder-plus --task "..."
export MOONSHOT_API_KEY=sk-...
coder -m moonshot/kimi-k2.5 --task "..."
export MINIMAX_API_KEY=...
export MINIMAX_API_BASE=https://api.minimax.io/v1
coder -m minimax/minimax-m2 --task "..."
```

Three things to know:

- **`qwen/` is not a provider.** The Alibaba models live under `dashscope/`
  (or `qwen_ai_platform/`, the same thing under its old name). `qwen/` is the
  name of a model family, not of a route.
- **The window comes from the model name.** The context window is looked up by
  the part after the provider: `qwen` 32k, `deepseek` 64k, `kimi` 256k,
  `minimax` 200k, `claude` 200k, `gpt-` 128k, `gemini` 1M. When the model is
  new or the family is not in the table, set it yourself:
  `context.context_window: 262144`.
- **The model has to call tools.** The agent only works with a model that
  supports tool calling. The cheap models of a family usually do not, so keep
  them for `model.routing.cheap` only if they do.

The routing is what makes a mixed setup work: the main model does the work,
the cheap one does the looking around.

```yaml
model:
  model_name: dashscope/qwen3-coder-plus
  routing:
    cheap: moonshot/kimi-k2.5
    summarize: moonshot/kimi-k2.5
```

#### The aliases of a litellm config file

An endpoint that is not in the table above can have an alias. `model.litellm_config`
names a litellm config file, and the `model_list` of that file names the models:

```yaml
# ~/.coderagent/litellm_config.yaml
model_list:
  - model_name: nengpa/minimax-m2.7
    litellm_params:
      model: openai/MiniMax-M2.7
      api_base: https://api.nengpa.com/v1
      api_key: sk-cp-...
```

```yaml
# ~/.coderagent/config.yaml
model:
  model_name: nengpa/minimax-m2.7
  litellm_config: ~/.coderagent/litellm_config.yaml
```

The alias `nengpa/minimax-m2.7` is then a model like any other: `coder -m
nengpa/minimax-m2.7 --task "..."` works, and so does the routing.

The `model` of an entry is the model litellm calls, with the provider in front of
it. The other parameters of the entry go to litellm as they are, so the key of a
third party endpoint stays in that one file instead of the configuration of the
agent. The settings of `model.model_kwargs` win over the ones of the alias.

The `api_base` stops at `/v1`: litellm appends `/chat/completions` to it.

### The tools

| Tool | What it does |
|---|---|
| `read` | Read a file. `offset` and `limit` cut a long file into pieces. |
| `write` | Write a file from scratch. |
| `edit` | Replace a piece of text in a file. |
| `multi_edit` | Several edits in one file, in order. |
| `glob` | The files that match a pattern, e.g. `**/*.py`. |
| `grep` | Search for a regular expression. `glob` limits the files. |
| `ls` | List a directory. `depth: -1` lists everything below it. |
| `bash` | Run a command. `run_in_background` returns a task id at once. |
| `bash_output` | The output of a background command. |
| `bash_kill` | Stop a background command. |
| `todo_write` | The task list of the agent. Shown at the bottom of the interface. |
| `task` | Hand a job to a sub agent. |
| `skill` | Load the instructions of a skill. |

`tools.enabled` is the list of the tools the model may call, `tools.disabled`
takes some of them away. The tools of the MCP servers are always there.

### The permissions

The mode decides what the agent may do without asking:

| Mode | What it does |
|---|---|
| `default` | Reading is free, writing and commands are asked for |
| `acceptEdits` | Writing is free, commands are asked for |
| `plan` | Nothing is changed. The agent only reads and answers. |
| `readonly` | Like `plan`, but the agent is told to describe the change instead of making it |
| `bypass` | Everything is allowed. For a container or a throwaway checkout. |

The mode can be changed while the session runs, with `/mode` or `/plan`.

`plan` and `readonly` take the writing tools away from the model, so the model
is told about it: a `<permission_mode mode="...">` block goes into the
conversation, saying what it may do and what it should answer instead. The
block follows the mode, so it changes as soon as the mode changes.

The rules are more precise than a mode. A rule has a tool, a pattern and a
decision:

```yaml
permissions:
  rules:
    - tool: edit
      pattern: "tests/**"
      decision: allow
    - tool: bash
      pattern: "rm -rf"
      decision: deny
      reason: that command is not allowed
```

The pattern is a glob for the tools that touch a path (`read`, `write`,
`edit`, `multi_edit`, `glob`, `grep`, `ls`) and a regular expression for
`bash`, where it is matched against the beginning of each part of the command.
The decision is `allow`, `ask` or `deny`. The last rule that matches wins.

The rules of the project live in `.coderagent/rules.yaml`, the rules of the
user in `~/.coderagent/rules.yaml`. Both are read, in that order, so a rule of
the user beats a rule of the project with the same tool and pattern:

```yaml
# .coderagent/rules.yaml
rules:
  - tool: bash
    pattern: "pytest"
    decision: allow
```

`permissions.deny_paths` are the paths that are off limits, whatever the mode
says. `permissions.include_dirs` are the directories outside the working
directory that the agent may still touch. Without them the agent stays inside
the directory of the session.

The shell has its own boundaries: the commands that only look around (`ls`,
`cat`, `grep`, `git status`) go through without a question, the ones that
destroy something or send it out (`rm`, `curl`, `git push`) ask, and a path
outside the working directory is refused in every mode.

`/permissions` shows the mode and the rules that are in effect.

Without a terminal nobody can be asked, so a call that needs approval is
refused and the model is told why. In a script, use
`--permission-mode bypass` for the calls that need it.

### The context

The context of the model has a window (`context.context_window`, by default
the window of the model). When the context comes close to the limit, the
older part of it is replaced by a summary. The summary is written by another
model (`context.summarize_model`), the older messages are not thrown away:
they are in the summary.

| Option | What it does |
|---|---|
| `context_window` | The size of the window. By default the one of the model. |
| `compact_threshold` | When to compact, as a share of the window. |
| `keep_recent_turns` | The turns that are never compacted. |
| `keep_recent_token_ratio` | The share of the window that is always kept. |
| `compact_every_turns` | Compact after that many turns, even when the window is free. |
| `reserved_output` | The room that is kept for the answer of the model. |
| `auto_compact` | Whether the agent compacts on its own. |

`/compact` compacts now.

### The memory

At the end of a session the agent asks the model what is worth remembering.
The facts about the project are written right away, the preferences of the
user wait for a confirmation.

```bash
/memory                # the memory of the project and of the user
/memory confirm        # write the pending preferences
/memory forget <text>  # remove a fact
```

The project memory is `.coderagent/memory/projects.md`, the preferences of the
user are `~/.coderagent/CLAUDE.md`. `memory.enabled: false` turns the whole
thing off, the model is not even asked. See [Memory](coderagent_memory.md).

### The checkpoints

Before a file is written, the agent takes a checkpoint of it. The checkpoints
are kept per session, the last 50 of them (`checkpoint.keep`). `/rewind` lists
them, and with an id it puts the files back and rolls the conversation back to
that point:

```bash
/rewind                 # the checkpoints of the session
/rewind 20261106-a1b2c3  # put the files of that checkpoint back
```

`checkpoint.enabled: false` turns them off.

### The sandbox

The commands of the agent run in a sandbox. By default it is the machine of
the user:

```yaml
sandbox:
  type: local
```

`swerex_docker`, `swerex_modal`, `bubblewrap` and `contree` are the other
ones. The options of the sandbox go to the environment as they are:

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
  run_args: ["--rm", "--network", "none"]
```

The sandbox has no policy of its own: the network policy belongs to the
environment, the paths belong to the permission layer. See
[Sandbox](coderagent_sandbox.md).

## What the agent reads

The agent reads the instructions of the project before it starts. The files are
`AGENTS.md` and `CLAUDE.md`, in this order:

```bash
coder --task "/init"   # write an AGENTS.md for this project
```

The user file `~/.coderagent/CLAUDE.md` comes first, then the project. An
`AGENTS.md` in a subdirectory is read when the agent touches something in it.

## What the agent can delegate

### The sub agents

A sub agent works in its own context and returns a conclusion, so the main
context stays clean. The agent calls the `task` tool when a job is too big for
the main context: searching the whole code base, changing the same pattern
everywhere, checking a result on its own.

Three of them are always there:

| Name | What it does | Tools |
|---|---|---|
| `code-explorer` | Find code, follow a call chain | `read`, `grep`, `glob`, `ls` |
| `verifier` | Run the tests, reproduce the bug | `read`, `grep`, `glob`, `bash` |
| `refactorer` | Change the same pattern everywhere | `read`, `edit`, `grep`, `glob` |

Your own sub agents are markdown files in `.coderagent/agents`:

```markdown
---
name: doc-writer
description: Write the documentation of a module.
tools: [read, grep, glob]
model_purpose: cheap
max_turns: 15
---
You write the documentation of a module. Read the code, then write the docs.
```

The tools are a white list: the sub agent cannot reach anything else. The
files of the user are in `~/.coderagent/agents`. See
[Sub agents](coderagent_subagents.md).

### The skills

A skill is a package of instructions, scripts and resources:

```
.coderagent/skills/pdf-report/
├── SKILL.md
├── scripts/
│   └── make_report.py
└── assets/
    └── template.docx
```

```markdown
---
name: pdf-report
description: Make a PDF report out of a folder of notes.
---
Run `scripts/make_report.py` to build the report...
```

The model sees the name and the description of every skill, and loads the
whole one when the description fits the task. The files of the user are in
`~/.coderagent/skills`. See [Skills](coderagent_skills.md).

### The plugins

A plugin adds tools, commands or hooks to the agent. It is a directory
with a `plugin.py` in it, and it runs in the process of the agent, without a
sandbox. A plugin is only loaded when it is trusted:

```bash
/plugins            # the plugins that were found
/plugins trust hello
```

See [Plugins](coderagent_plugins.md).

### The hooks

A hook is a command of yours that runs at an important moment of the session:
before a tool runs, after it ran, when the session starts or ends. A hook can
block an action, rewrite its arguments or add something to the context.

```yaml
hooks:
  events:
    PreToolUse:
      - matcher: "bash"
        hooks:
          - type: command
            command: ./scripts/guard.sh
```

See [Hooks](coderagent_hooks.md).

### The MCP servers

The tools of an [MCP](https://modelcontextprotocol.io) server are available
under the name `mcp__<server>__<tool>`. The MCP SDK is optional:

```bash
pip install "mini-swe-agent[mcp]"
```

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx -y @modelcontextprotocol/server-filesystem .
```

See [MCP servers](coderagent_mcp.md).

## The sessions and the money

A session is an append-only log of events, and that log is the source of
truth. The sessions live in `~/.coderagent/sessions`, one file per session.

```bash
coder --list              # the sessions of this directory
coder --resume <id>       # continue one of them
coder --fork <id>         # continue a copy of one of them
```

Inside the interface, `/clear` starts a new session, `/resume` and `/fork` do
the same as on the command line.

`/cost` shows what the session has cost and where the money went:

```
model: deepseek/deepseek-flash
calls: 9
tokens in the context: 120433
cost so far: $0.4200
cost: $0.4200
by purpose:
  main        $0.3800
  cheap       $0.0400
```

The bill belongs to the session: a new session starts at zero, whatever the
session before it spent. The same number is in the trace, in `/status` and in
the `session_cost` of the command line.

## The files

| Path | What it is |
|---|---|
| `.coderagent/config.yaml` | The configuration of the project |
| `.coderagent/rules.yaml` | The permission rules of the project |
| `.coderagent/agents/*.md` | The sub agents of the project |
| `.coderagent/skills/*/SKILL.md` | The skills of the project |
| `.coderagent/plugins/*/plugin.py` | The plugins of the project |
| `.coderagent/commands/*.md` | The commands of the project |
| `.coderagent/memory/projects.md` | What the agent remembers about the project |
| `.coderagent/pending-memory.md` | The preferences that wait for a confirmation |
| `AGENTS.md`, `CLAUDE.md` | The instructions of the project |
| `~/.coderagent/config.yaml` | The configuration of the user |
| `~/.coderagent/litellm_config.yaml` | The aliases of the models |
| `~/.coderagent/rules.yaml` | The permission rules of the user |
| `~/.coderagent/CLAUDE.md` | The instructions and the preferences of the user |
| `~/.coderagent/agents/`, `~/.coderagent/skills/`, `~/.coderagent/plugins/` | The extensions of the user |
| `~/.coderagent/trusted-plugins.json` | The plugins the user trusts |
| `~/.coderagent/sessions/` | The event log of the sessions |
| `~/.coderagent/checkpoints/` | The checkpoints of the sessions |

`MSWEA_CODER_HOME` moves the whole user directory somewhere else.
