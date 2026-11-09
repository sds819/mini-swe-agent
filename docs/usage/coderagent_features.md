# The features of the coding agent

A list of everything `coder` can do, one line per feature. The pages that
describe a part in detail are linked at the end of each section.

> 中文版：[coding agent 的功能](coderagent_features_zh.md)

## The ways to run it

- **One turn from the terminal** — `coder -t "fix the failing test"`. The
  answer is printed as text, or as JSON with `--output-format json`.
- **The terminal interface** — `coder` without a task, or `coder --tui`. A
  full screen interface with a status bar, tool cards and approvals.
- **The browser** — `coder web`. The same agent in a chat page, with a
  settings page for the model.
- **As an API** — every action of the browser is a plain HTTP call, so a
  script can drive the agent.
- **As a library** — `coderagent.run.run_turn` and `build_loop` put the agent
  into another Python program.
- **In a benchmark** — the run scripts of mini-swe-agent solve SWE-bench and
  ProgramBench with the same model interface.

## The models

- **Any provider litellm knows** — OpenAI, DeepSeek, Anthropic, Gemini,
  Mistral, OpenRouter, … The provider in front of the name says who is
  called: `deepseek/deepseek-flash`.
- **Third party endpoints** — an OpenAI compatible address in `api_base`, with
  its own key. The address may be pasted with the `/chat/completions` at the
  end; the part behind `/v1` is cut off, because litellm adds it itself.
- **Aliases** — a litellm config file with a model list. The model name can
  then be an alias of that list, and the key of the endpoint stays in the file.
- **Cache control** — `set_cache_control: ephemeral` for the providers that
  support it.
- **Retries** — `max_retries`, three by default.
- **Routing by purpose** — a different model for `main`, `cheap`, `summarize`,
  `reflect` and `strong`.
- **Routing by the state of the session** — a rule like `tokens > 50000`
  switches to another model, and the reason is in the event log.
- **A separate model for the summary** — `context.summarize_model`, empty
  means the model of the agent.
- **Streaming** — the answer arrives piece by piece, in the terminal and in
  the browser.

## The tools

The thirteen built-in tools:

| Tool | What it does |
|---|---|
| `read` | Read a file, with the line numbers |
| `write` | Write a file, creating it if needed |
| `edit` | Replace one exact string in a file |
| `multi_edit` | Several edits in one file — all of them, or none |
| `glob` | Find files by pattern (`*` in one segment, `**` across directories) |
| `grep` | Search the contents with a regular expression, by lines, by file or by count |
| `ls` | List a directory; `depth: -1` walks the whole tree |
| `bash` | Run a shell command, with a timeout or in the background |
| `bash_output` | The output of a background command so far |
| `bash_kill` | Kill a background command |
| `todo_write` | The task list of the current work |
| `task` | Hand a self contained job to a sub agent |
| `skill` | Load the instructions of a skill |

- **Tools of MCP servers** — `mcp__<server>__<tool>`, from every server that
  is configured.
- **Tools of plugins** — a plugin can add tools, commands and hooks.
- **The schemas are trimmed to the budget** — when the tools do not fit in
  the context, the ones that matter least go first. `bash` and `read` are
  never dropped.
- **The tool set is configurable** — `tools.enabled` is the list of the tools
  the model may call, `tools.disabled` takes single ones away.

## The permissions

- **Five modes** — `default`, `acceptEdits`, `plan`, `readonly` and `bypass`.
- **The model is told** — in `plan` and `readonly` the agent knows that it may
  not change anything, and answers with what it found instead.
- **Rules** — `~/.coderagent/rules.yaml` and `.coderagent/rules.yaml` decide
  per tool and per pattern. The user level file wins.
- **`Always allow`** — the button of an approval writes a rule, so the same
  tool goes through from then on.
- **Denied paths** — `permissions.deny_paths`, paths the agent may not touch.
- **Extra directories** — `permissions.include_dirs`, directories outside the
  working directory the agent may still touch.
- **Three answers** — allow, deny, always allow. Nobody answers, the call is
  denied: in the browser after `ui.approval_timeout` seconds (five minutes by
  default), in the terminal after no limit at all, because somebody is there.
- **In the terminal** the answer is picked with the arrow keys, in the browser
  with the buttons of the card. Without a terminal the answer is a denial.
- **Hooks run before the permission check** — a hook may rewrite the call or
  block it, and then the permission check sees the rewritten call.

## The sessions

- **New, listed, continued, copied** — `--resume`, `--continue`, `--fork` and
  `--list`.
- **The event log is the truth** — every message, tool call, result and cost
  is appended to a JSONL file. A session is rebuilt by replaying it.
- **Checkpoints** — a snapshot of the file before every write. `/rewind` rolls
  back to one.
- **`/clear`** — starts a new session and keeps the old one in the log.
- **The money** — tokens and cost per session, in the status bar, in `/cost`
  and in the trace.
- **The trace** — `coder export --format json|otel` writes the session out,
  for a dashboard or for OpenTelemetry.

## The context

- **The tokens are counted** — with tiktoken when it is installed, otherwise
  an estimate.
- **The window follows the model** — 64k for DeepSeek, 200k for Claude, 128k
  for GPT, and so on. A configured `context_window` wins over the table.
- **Automatic compression** — when the conversation reaches 80 % of the
  window, it is summarized and the history is shortened. The summary is a
  structure: goal, findings, decisions, files touched, open questions, next
  steps, errors seen.
- **What is kept** — the last turns, or the last 40 % of the tokens, whichever
  is more.
- **`/compact`** — compress on demand.
- **The order of the messages** — system prompt, the instruction files, the
  todo list, the summary of the session, then the history.

## The memory

- **The memory of the project** — `.coderagent/memory`, written at the end of
  a turn with what was learned about the project.
- **The memory of the user** — `~/.coderagent/CLAUDE.md`, with the
  preferences of the user.
- **Preferences wait for a confirmation** — they land in
  `pending-memory.md` first, and `/memory confirm` writes them.
- **The instruction files** — `AGENTS.md` and `CLAUDE.md` of the project, and
  the `CLAUDE.md` of the user, are read by the agent.
- **It can be switched off** — `memory.enabled`.

## The extensions

- **Sub agents** — `.coderagent/agents/*.md`: a name, a description, a system
  prompt, a list of tools and a maximum number of turns. `code-explorer`,
  `verifier` and `refactorer` come with the agent. The model sees the index
  of them, so it can call them by name.
- **Skills** — `.coderagent/skills/<name>/SKILL.md`: a package of steps,
  scripts and templates for a kind of task. The agent loads one when it fits.
- **Plugins** — `.coderagent/plugins`: a Python module that adds tools,
  commands and hooks. A plugin has to be trusted once.
- **Hooks** — six moments: `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `Stop` and `SessionEnd`. A hook is a command that reads
  JSON and answers JSON: allow, deny or block, with a reason, with extra
  context or with rewritten arguments.
- **Your own commands** — `.coderagent/commands/*.md`: a slash command with a
  description, an argument hint, the tools it may use and its own model.
- **MCP servers** — a server over stdio or over http. Its tools join the
  tools of the agent, they ask for permission like every other tool, and the
  connection is made again when it breaks.

## The sandbox

- **Local by default** — the commands run in the working directory.
- **Or in a container** — `docker`, `singularity`, `bubblewrap`, `contree`,
  and the remote sandboxes of SWE-rex. The same environments as
  mini-swe-agent.
- **Only `bash` goes into the sandbox** — the file tools stay in the working
  directory.
- **`/sandbox`** — says where the commands run.

## The terminal interface

- **The answer streams in** — the text and the reasoning.
- **The status bar** — the model, the tokens, the cost, the directory and the
  permission mode.
- **The tool cards** — the call, the output and the diff of the change.
- **The approval** — `y`, `n` and `a`, or the arrow keys on a numbered list.
- **Long output is folded away** — the interesting part stays visible.
- **The todo panel** — the task list of the current work.

## The web interface

- **The chat page** — three columns: the sessions and the files on the left,
  the conversation in the middle, the status, the changes and the file on the
  right.
- **The answer streams in** — over a server sent event stream, and a browser
  that comes late reads the whole answer.
- **The settings page** — the model as a form, the layer every field comes
  from, the preview of all the layers with the secrets taken out.
- **Test the connection** — one cheap call, and it says whether the model
  calls the tools at all.
- **Test a model** — a panel for an endpoint, a key and a model name, without
  writing anything.
- **The permissions in two places** — the settings page for the next
  session, the chat page for the session that is running, right away.
- **The approvals in the browser** — the same three answers.
- **The languages** — English and Chinese. The switch in the top bar changes
  the whole page without a reload, and the choice is remembered in the
  browser and in a cookie. The region of the address decides when the
  visitor has not chosen.
- **The security model** — no authentication, `127.0.0.1` by default, a
  header that a cross site request cannot send, a path that cannot leave the
  working directory, and a key that is only shown when it is asked for.

## The configuration

- **Four layers** — the defaults of the package, the project file
  `.coderagent/config.yaml`, the user file `~/.coderagent/config.yaml`, and
  the overrides of the command line (`-c key=value`). The later wins.
- **The sections** — `model`, `agent`, `tools`, `permissions`, `context`,
  `memory`, `checkpoint`, `mcp`, `hooks`, `ui` and `sandbox`.
- **The paths** — `MSWEA_CODER_HOME` moves the user level files somewhere
  else.
- **The settings page writes the user file only** — the project file is in
  the repository and is never written.

## The commands

Twenty-four built-in commands: `/help`, `/model`, `/mode`, `/plan`,
`/compact`, `/clear`, `/resume`, `/fork`, `/rewind`, `/diff`, `/init`,
`/cost`, `/todos`, `/mcp`, `/permissions`, `/hooks`, `/agents`, `/skills`,
`/plugins`, `/memory`, `/status`, `/sandbox`, `/export` and `/context`.

Your own commands live in `.coderagent/commands/*.md` and join them.

## The benchmark part of mini-swe-agent

- **`mini`** — a run script: a task, a model, an environment, and a
  trajectory file.
- **SWE-bench** — the whole dataset, in parallel, with a slice and a filter.
- **SWE-bench, one instance** — for a single problem.
- **ProgramBench** — the programming benchmark.
- **The inspector** — reads a trajectory file and shows what the agent did.
- **The environments** — local, docker, singularity, bubblewrap, contree,
  SWE-rex docker and SWE-rex modal.
- **The models** — litellm for most providers, and portkey, openrouter,
  requesty, the text based models and the roulette model besides.

## Where the details are

| Page | What is in it |
|---|---|
| [The coding agent](coderagent.md) | The whole thing, from the first session to the files |
| [The commands](coderagent_commands.md) | Every command and the ones of your own |
| [The web interface](coderagent_web.md) | The chat page, the settings page, the API |
| [Sub agents](coderagent_subagents.md) | Writing a sub agent |
| [Skills](coderagent_skills.md) | Writing a skill |
| [Hooks](coderagent_hooks.md) | The six moments and what a hook answers |
| [Plugins](coderagent_plugins.md) | Writing a plugin |
| [MCP servers](coderagent_mcp.md) | The configuration of a server |
| [The memory](coderagent_memory.md) | The files and the confirmation |
| [Model routing](coderagent_routing.md) | The purposes and the rules |
| [The sandbox](coderagent_sandbox.md) | The environments |
| [Trace export](coderagent_export.md) | The trace of a session |
| [Quick start](coderagent_quickstart.md) | The first ten minutes (中文) |
