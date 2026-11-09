# The features of the coding agent

A list of everything `coder` can do, one line per feature, with an example and
the errors of every part. The pages that describe a part in detail are linked at
the end of each section.

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

### Example

```bash
# One turn, the answer as text.
coder -t "add a docstring to src/app.py"

# One turn, the answer as JSON (for a script).
coder -t "list the files of this directory" --output-format json

# The terminal interface.
coder                      # with a terminal this is the TUI
coder --tui                # the same, said explicitly

# The browser.
coder web --cwd . --port 8765

# A session of this directory, the newest first.
coder --list
```

The JSON of one turn has the fields `session_id`, `messages`, `cost`, `usage`,
`stop_reason` and `error`:

```json
{
  "session_id": "20261109-3f0a91",
  "messages": [{"role": "assistant", "content": "I added the docstring."}],
  "cost": 0.0012,
  "usage": {"input_tokens": 4210, "output_tokens": 96},
  "stop_reason": "end_turn",
  "error": ""
}
```

`stop_reason` is one of `end_turn`, `max_turns`, `cost_exceeded`, `error` and
`interrupted`.

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `no task given` | No `-t`, no `--tui`, and stdin is not a terminal (a script, a pipe). | Give a task: `coder -t "..."`. |
| `session 20261109-3f0a91` | The same as above, but a session was found to continue. | Same; add `-t` to run a turn in it. |
| `Unknown command '/foo'. Try /help.` | The line started with `/` but no command has that name. | Check the spelling, or `/help` for the list. |
| `ValueError: 'bogus' is not a valid PermissionMode` | `--permission-mode bogus` — the flag is checked when the policy is built, and the exception is not caught. | Use one of `default`, `acceptEdits`, `plan`, `readonly`, `bypass`. |
| `ValueError: Unknown output format: xml` | `--output-format` accepts only `text` and `json`. | Use `text` or `json`. |
| `Unknown format 'xml'. Use json or otel.` | `coder export --format` accepts only `json` and `otel`. | Use `json` or `otel`. |
| `no sessions yet` | `--list` found no session in this directory. | Nothing to do; run a turn first. |
| `coder web: cannot listen on 127.0.0.1:8765 (Address already in use).` on stderr, exit code 1 | The port is taken. The server checks this itself before it starts, because uvicorn's own error does not say what to do. | Use another port: `coder web --port 8766`. |

`coder` exits with `0` after a normal turn, whatever the answer was, and with
`1` when it could not start at all (a bad flag value, a port that is taken).

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

### Example

```bash
# The provider is the part in front of the slash.
coder -t "..." -m deepseek/deepseek-flash

# A third party endpoint that speaks the OpenAI protocol.
coder -t "..." -m openai/MiniMax-M2.7 \
  -c model.model_kwargs.api_base=https://api.example.com/v1 \
  -c model.model_kwargs.api_key=sk-...
```

```yaml
# .coderagent/config.yaml
model:
  model_name: deepseek/deepseek-flash
  set_cache_control: ephemeral
  routing:
    main: deepseek/deepseek-chat
    cheap: deepseek/deepseek-flash
    summarize: deepseek/deepseek-flash
  routing_rules:
    - when: "tokens > 50000"
      purpose: strong
```

The model of a turn is decided in this order:

1. the model the user picked with `/model` (it wins over everything),
2. the first `routing_rules` entry whose condition holds,
3. the automatic policy: the budget is nearly used up → `cheap`, the context is
   big (> 50000 tokens) or the session is long (> 30 turns) → `strong`,
4. `routing.main`, and without it the model of the agent.

When the model changes, the event log says why:

```
Switched from deepseek/deepseek-flash to deepseek/deepseek-chat: the context has grown
```

The reasons are `the budget is nearly used up`, `the context has grown`,
`the session has many turns`, `the rule '<when>' holds` and
`the rules of the routing say so`.

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `LLM Provider NOT provided` | The model name has no provider in front of it. | Write `openai/<name>` for an OpenAI compatible endpoint, or `deepseek/<name>`. |
| `ValueError: Invalid mode: {mode}` | `set_cache_control` is neither `default_end` nor `ephemeral`. | Use one of the two, or remove the line. |
| `the file does not exist` | `model.litellm_config` points at a file that is not there. | Fix the path; it is relative to the working directory. |
| `the file is not valid YAML: {error}` | The alias file cannot be parsed. | Fix the YAML. |
| `the file has no model_list` | The alias file has no `model_list`. | Add the list of the models with their `litellm_params`. |
| `'{name}' is not one of the aliases of this file` | The model name is not in the `model_list` of the alias file. | Use one of the aliases, or drop `litellm_config`. |
| `BadRequestError` | The provider refused the request (a wrong key, a wrong name, a wrong parameter). | It is **not** retried; the message of the provider is the answer. |
| `AuthenticationError` | The key is missing or wrong. | Set `model.model_kwargs.api_key`, or the key of the endpoint in the alias file. |
| `ContextWindowExceededError` | The request was larger than the window of the model. | Lower `context.context_window`, or use a model with a bigger window. |

Retries are a separate thing from the errors above: a rate limit or a timeout
is retried, a bad request is not. The number of attempts comes from
`MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT` and is **10** by default.
`coder web` sets that variable from `model.max_retries` (3 by default), so in
the browser the number of attempts follows the configuration, while in the
terminal it does not.

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

### Example

```bash
# The model calls these, but you can call them yourself to try them out.
```

```json
{"tool": "read", "params": {"path": "src/app.py"}}
{"tool": "edit", "params": {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 2"}}
{"tool": "grep", "params": {"pattern": "def main", "output_mode": "files_with_matches"}}
{"tool": "glob", "params": {"pattern": "src/**/*.py"}}
{"tool": "ls", "params": {"path": "src", "depth": -1}}
{"tool": "bash", "params": {"command": "pytest -q", "timeout": 300}}
{"tool": "bash", "params": {"command": "pytest -q", "background": true}}
{"tool": "bash_output", "params": {"task_id": "b7f3"}}
```

`multi_edit` takes a list and is all or nothing:

```json
{"tool": "multi_edit", "params": {"path": "src/app.py", "edits": [
  {"old_string": "import os", "new_string": "import os\nimport sys"},
  {"old_string": "def main():", "new_string": "def main(argv=None):"}
]}}
```

`grep` has three modes: `content` (the default), `files_with_matches` and
`count`. It returns at most 100 matches, `glob` at most 200 files.

### When something goes wrong

Every tool answers with an `Error: ...` line instead of raising, so the model
sees the message and can correct itself. The messages are:

| Tool | Message |
|---|---|
| `read` | `Error: file not found: {path}. Use \`ls\` to see what is in that directory.` |
| `read` | `Error: '{name}' is a directory. Use \`ls\` to list it.` |
| `read` | `Error: '{name}' is a binary file.` |
| `edit` | `Error: old_string not found in {path}. Use \`read\` to see the exact content, then retry with more context.` |
| `edit` | `Error: old_string is not unique in {path}: it appears {count} times (lines {...}). Use more context to make it unique.` |
| `multi_edit` | `Error: Edit #1 failed, no changes were written. {inner}` — the file is untouched. |
| `grep` | `Error: invalid regular expression '{pattern}': {error}` |
| `grep` | `Error: \`output_mode\` must be one of content, files_with_matches, count (got '{mode}').` |
| `glob`/`grep`/`ls` | `Error: path not found: {path}.` / `Error: not a directory: {path}.` |
| `bash` | `Error: \`command\` is required and must be a non-empty string.` |
| `bash_output` | `Error: unknown task id '{id}'.` |
| `todo_write` | `Error: todo #1 has invalid status '{status}'. Use one of pending, in_progress, completed.` |
| `task` | `Error: unknown sub agent '{name}'. Available sub agents: {...}.` |
| `skill` | `Error: unknown skill '{name}'. Available skills: {...}.` |

The errors of the executor itself are raised inside the result of the call:

| Message | Meaning |
|---|---|
| `Error: unknown tool '{name}'. Available tools: {...}.` | The model called a tool that is not registered — usually because `tools.enabled` was narrowed. |
| `Error: permission denied for '{tool}'. {reason}` | A rule or a mode refused the call. |
| `Error: the user denied '{tool}'.` | Somebody pressed `n` at the approval. |
| `Error: '{tool}' needs approval but no approver is available. Run with --permission-mode bypass to allow it.` | A call that needed approval in a headless run. `--permission-mode bypass` or a rule that allows it. |
| `Error: the hook blocked '{tool}'. {reason}` | A `PreToolUse` hook refused the call. |
| `Error: '{tool}' failed: {type}: {e}` | The tool itself raised. |

A `bash` call that ends with a non-zero exit code is **not** an error: the exit
code is part of the output, as `[exit code 1]`. A command that runs longer than
`tools.bash_timeout` (120 seconds by default) fails with:

```
An error occurred while executing the command: Command 'sleep 60' timed out after 120 seconds
```

A background command answers with `Started background task {id}: {cmd}` and is
read with `bash_output`, killed with `bash_kill`.

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

### Example

The mode decides what happens without any rule:

| Mode | `read`, `glob`, `grep`, `ls` | `write`, `edit`, `multi_edit` | `bash` | `todo_write`, `bash_output`, `bash_kill` |
|---|---|---|---|---|
| `default` | allow | ask | ask | allow |
| `acceptEdits` | allow | allow | ask | allow |
| `plan` | allow | deny | deny | allow |
| `readonly` | allow | deny | deny | allow |
| `bypass` | allow | allow | allow | allow |

A rule file decides per tool and per pattern:

```yaml
# ~/.coderagent/rules.yaml
rules:
  - tool: bash
    pattern: "pytest"
    decision: allow
    reason: the test suite is safe to run
  - tool: edit
    pattern: "src/**/*.py"
    decision: allow
  - tool: "*"
    pattern: "*"
    decision: ask
```

`pattern` is a glob for the path tools (`*` in one segment, `**` across
directories), a **regular expression** for `bash`, and the tool name for
everything else.

```bash
coder -t "run the tests" --permission-mode acceptEdits
coder -t "how would you fix this?" --permission-mode plan
```

`plan` and `readonly` put a note into the messages the model sees:

```xml
<permission_mode mode="plan">
You are in plan mode. You may only look around: `read`, `glob`, `grep` and `ls`
work, but every tool that changes something, `bash` included, is refused.
Investigate the task and answer with the plan you would follow. The user
decides whether it is executed.
</permission_mode>
```

`Always allow` at an approval writes a rule into `~/.coderagent/rules.yaml`:

```yaml
rules:
  - tool: bash
    pattern: pytest
    decision: allow
    reason: always allowed
```

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `Error: permission denied for 'write'. '{path}' is outside the working directory {cwd}` | The agent tried to touch a path outside the working directory. | Add the directory to `permissions.include_dirs`, or change the working directory. |
| `Error: the user denied 'write'.` | Somebody refused the approval. | Allow it, or write a rule for it. |
| `Error: 'write' needs approval but no approver is available. Run with --permission-mode bypass to allow it.` | The run had no terminal (a script or a CI job) and the tool needed approval. | `--permission-mode bypass`, or a rule with `decision: allow`. |
| `{path}:{line}: invalid decision '{d}', expected one of allow, ask, deny` | The rule file has a wrong decision. | Use `allow`, `ask` or `deny`. |
| `{path}:{line}: unknown rule keys: {keys}` | The rule has a key that does not exist. | The keys are `tool`, `pattern`, `decision` and `reason`. |
| `{path}: invalid YAML: {error}` | The rule file cannot be parsed. | Fix the YAML; the message has the line. |
| `{path}: \`rules\` must be a list` | The `rules` key is not a list. | Make it a list of mappings. |

A rule with `decision: allow` does **not** open the disk: a path outside the
working directory stays outside, unless it is in `permissions.include_dirs`.
The rules of the user cannot widen the bounds.

`permissions.deny_paths` adds a rule that denies everything that matches, and
it is applied after the rule files, so it wins over an `allow` of the same
path.

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

### Example

```bash
coder -t "first task"                     # a new session
coder --list                              # the sessions of this directory
coder --resume 20261109-3f0a91 -t "more"  # continue that one
coder --continue -t "more"                # continue the newest of this directory
coder --fork 20261109-3f0a91 -t "other"   # a copy, the original stays
```

The files of a session live in `~/.coderagent/`:

```
~/.coderagent/sessions/20261109-3f0a91.jsonl        # the event log
~/.coderagent/sessions/20261109-3f0a91.meta.json    # id, cwd, created_at, model_name
~/.coderagent/checkpoints/20261109-3f0a91.json       # the snapshots of the writes
```

The event log is one JSON object per line, and the types are `user_message`,
`assistant_message`, `tool_call`, `tool_result`, `compaction`, `error` and
`turn_end`.

`/rewind` restores the **files** only — what a command did to the outside
world stays done — and truncates the history of the session to the moment of
the snapshot.

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `ValueError: no checkpoint '<id>' in this session` | `/rewind` was given an id that is not a checkpoint of this session. | `/rewind` without an id lists the checkpoints. |
| `/resume <unknown id>` starts a session with the directory `.` | A session id that is not in the log does not fail — it makes an empty session. | Check the ids with `coder --list`. |
| A turn ends with `stop_reason: max_turns` | The agent made 50 model calls (`agent.max_turns`) without finishing. | Raise `agent.max_turns`, or make the task smaller. |
| A turn ends with `stop_reason: cost_exceeded` | The turn cost more than `agent.cost_limit`. `0` means no limit. | Raise `agent.cost_limit`. |
| A turn ends with `stop_reason: error` | The model call failed after the retries. The text of the error is in `error`. | Look at `error`; it is the message of the provider. |
| A turn ends with `stop_reason: interrupted` | Somebody pressed `ctrl+c`. | The session is saved; continue it with `--resume`. |

A turn that ended with `cost_exceeded` or `error` is **not** reflected on: the
memory of the session keeps what was learned before the failure.

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

### Example

```yaml
context:
  context_window: 64000
  compact_threshold: 0.8
  keep_recent_turns: 20
  keep_recent_token_ratio: 0.4
  compact_every_turns: 40
  summarize_model: deepseek/deepseek-flash
```

Without `context_window` in the configuration the window follows the name of
the model: `gpt-` 128k, `claude` 200k, `deepseek` 64k, `qwen` 32k, `llama` 8k,
`gemini` 1M, `mistral` 32k, `kimi` 256k, `minimax` 200k, and 200k for
everything else.

The summary is a JSON object with these keys:

```json
{
  "goal": "fix the failing test in test_api.py",
  "findings": ["the timeout of the client is 5 seconds, the test needs 10"],
  "decisions": ["raise the timeout in the fixture"],
  "files_touched": ["tests/test_api.py"],
  "open_questions": [],
  "next_steps": ["run the suite again"],
  "errors_seen": ["TimeoutError after 5 seconds"]
}
```

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `... (nothing left to compact)` | The turn failed because the context was too big and there was nothing left to shorten. | Raise `context.context_window`, lower `context.reserved_output`, or `/clear` and start over. |
| The summary is a fallback instead of the real thing | The model answered with something that is not the JSON of the summary. It is tried twice, and the second time a conservative summary is used: the last five messages, with `next_steps: ["re-read the files that were mentioned to recover the details"]`. | Nothing to do — the session continues. Ask the model again for the details it lost. |
| `recent_errors` is empty although the session had errors | Only the tool messages that start with `Error:` are collected, and only the last three of them. | Nothing to do. |

The token count is exact with tiktoken and an estimate without it:
`int(chars / 3.6) + 4 * len(messages)`. An estimate that is too small delays
the compression, so installing tiktoken is worth it for a long session.

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

### Example

The three files:

```
.coderagent/memory/projects.md        # what the agent learned about the project
.coderagent/pending-memory.md         # the preferences, waiting for a confirmation
~/.coderagent/CLAUDE.md                # the preferences that were confirmed
```

At the end of a turn the agent looks at the last 40 messages and writes what
it found:

```markdown
# Project memory

- the tests of the API are run with `pytest tests/`, they need a postgres on localhost
- the release is made with `bump2version`, not with a manual edit of setup.py
```

A preference of the user goes to `pending-memory.md` first:

```markdown
# Preferences waiting for a confirmation

- always answer in Chinese
```

and only lands in `~/.coderagent/CLAUDE.md` after `/memory confirm`:

```markdown
## Preferences

- always answer in Chinese
```

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `The memory was not written: {path} would grow past 200 lines; tidy it up first.` | The file would become longer than 200 lines. | Shorten the file, or split it. |
| `The reflection of the session failed` (a warning in the log) | The model did not answer with the expected JSON, so nothing was written. The session is not harmed. | Nothing to do; the next turn tries again. |
| `Wrote 2 preference(s) to /Users/you/.coderagent/CLAUDE.md.` | The confirmation worked. | — |
| `Nothing like that in the memory.` | `/memory forget` did not find the text. | Check the text with `/memory`. |
| `Removed.` | `/memory forget` removed the text. | — |

The memory can be switched off entirely:

```yaml
memory:
  enabled: false
```

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

### Example

A sub agent, `.coderagent/agents/scout.md`:

```markdown
---
name: scout
description: Finds the place where a feature is implemented
tools: read, grep, glob, ls
model_purpose: cheap
max_turns: 15
---

You look for code. You never change anything. You answer with the files and
the line numbers.
```

The model calls it as a tool:

```json
{"tool": "task", "params": {"subagent_type": "scout", "description": "where is the auth?", "prompt": "find the auth code"}}
```

and the answer is a JSON object:

```json
{
  "status": "ok",
  "summary": "The auth is in src/auth/session.py.",
  "findings": ["src/auth/session.py:42 defines create_session"],
  "files_touched": [],
  "cost": 0.0004,
  "turns": 3,
  "purpose": "cheap"
}
```

A skill, `.coderagent/skills/release/SKILL.md`:

```markdown
---
name: release
description: How to make a release of this project
---

1. Run the test suite.
2. Run `bump2version patch`.
3. Push the tag.
```

A hook, in the configuration:

```yaml
hooks:
  events:
    PreToolUse:
      - matcher: "bash"
        hooks:
          - type: command
            command: ./.coderagent/hooks/check_secrets.sh
            timeout: 10
            strict: false
```

The hook reads JSON on stdin and answers JSON on stdout:

```json
{"decision": "block", "reason": "the command writes a secret"}
```

`decision` is `allow`, `deny` or `block`; the hook may also add
`additionalContext` or rewrite the call with `updatedInput`.

A custom command, `.coderagent/commands/commit.md`:

```markdown
---
description: Make a commit of the changes
argument-hint: [message]
allowed-tools: bash, read
model: cheap
---

Commit everything with the message: $ARGUMENTS
```

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `Error: unknown sub agent 'scout'. Available sub agents: code-explorer, refactorer, verifier.` | The name of the sub agent is not in the index. | Use one of the listed names; the index of the custom ones is in the system prompt. |
| `Error: the sub agents are not available in this session.` | The `task` tool is not registered — `tools.enabled` was narrowed. | Put `task` back into `tools.enabled`. |
| `Error: unknown skill 'release'. Available skills: {...}.` | The skill does not exist. | The skills are `.coderagent/skills/<name>/SKILL.md`. |
| `Trusted 'x'. It is loaded the next time the agent starts.` | The answer of `/plugins trust x`. | The plugin is used from the next session. |
| `Error: the hook blocked 'bash'. the command writes a secret` | A `PreToolUse` hook refused the call. | Fix the command, or fix the hook. |
| `Hook 'check_secrets.sh' timed out, ignoring it` | The hook took longer than its timeout. The call goes through. | Raise the `timeout`, or make the hook faster. |
| `Hook 'check_secrets.sh' failed with RuntimeError: ...` | The hook crashed. The call goes through. | Fix the hook. With `strict: true` the call is blocked instead. |
| `Error: the MCP server 'echo' is not connected.` | The server is not running. | Check the `command` of the server; `/mcp` says `not connected` or `failed: <error>`. |
| `Error: the MCP tool 'mcp__echo__echo' failed: RuntimeError: ...` | The server answered with an error. | The message of the server is in the answer. |

The custom commands are looked up in `<cwd>/.coderagent/commands/*.md` only —
the agent does not walk up the directories to find them.

## The sandbox

- **Local by default** — the commands run in the working directory.
- **Or in a container** — `docker`, `singularity`, `bubblewrap`, `contree`,
  and the remote sandboxes of SWE-rex. The same environments as
  mini-swe-agent.
- **Only `bash` goes into the sandbox** — the file tools stay in the working
  directory.
- **`/sandbox`** — says where the commands run.

### Example

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
```

The seven types are `local`, `docker`, `singularity`, `bubblewrap`, `contree`,
`swerex_docker` and `swerex_modal`. The options that the environment does not
know are ignored, so one file can carry the settings of several of them.

`/sandbox` answers with the environment that is in use:

```
local
```

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `ValueError: Unknown environment type: nope (resolved to nope, available: {...})` | The type is not one of the seven. | Use one of the names above. |
| `CalledProcessError: Command '[...]' returned non-zero exit status 1.` | The container could not be started, or the image could not be pulled. | Check the image name and that docker runs. |
| `FileNotFoundError: [Errno 2] No such file or directory: 'singularity'` | The binary of the environment is not installed. | Install it, or use another type. |
| The file tools touch the files of the host | Only `bash` goes into the sandbox. | That is by design: `read`, `edit` and friends work on the working directory of the session. |

## The terminal interface

- **The answer streams in** — the text and the reasoning.
- **The status bar** — the model, the tokens, the cost, the directory and the
  permission mode.
- **The tool cards** — the call, the output and the diff of the change.
- **The approval** — `y`, `n` and `a`, or the arrow keys on a numbered list.
- **Long output is folded away** — the interesting part stays visible.
- **The todo panel** — the task list of the current work.

### Example

The status bar looks like this:

```
deepseek/deepseek-flash | 1.5k/64k | $0.0000 | ~/work/project | default
```

An approval is a numbered list, and the selected one is marked:

```
1 [*] y allow
2 [-] n deny
3 [-] a always allow
```

`←`/`→` move the cursor, `↑`/`↓` do the same, the digits jump to a line, the
space toggles a multiple choice, `enter` confirms, and `y`, `n` and `a` answer
directly. `ctrl+c` interrupts the turn, `ctrl+q` settles the session and quits.

The todo panel marks the state of a task with `◉` (in progress), `◐` (pending)
and `○` (completed).

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Nothing happens when a tool wants approval | The terminal is not there — the run is headless. | The call is denied. Use `--permission-mode bypass` or a rule. |
| `▸ 42 more lines` under the output of a tool | The output was longer than the card. | The interesting part is visible; open the file, or run the command again with less output. |
| The interface does not start | `coder` without a task in a terminal starts the interface; without a terminal it prints `no task given`. | Use `coder --tui` to force it. |

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

### Example

```bash
coder web --cwd . --port 8765
```

```
coder web: http://127.0.0.1:8765
```

The API is plain HTTP. A message to a session:

```bash
curl -X POST http://127.0.0.1:8765/api/sessions/20261109-3f0a91/messages \
  -H 'X-Coder-Client: 1' -H 'Content-Type: application/json' \
  -d '{"text": "run the tests"}'
```

The stream of the events of a session:

```bash
curl -N http://127.0.0.1:8765/api/sessions/20261109-3f0a91/stream
```

The endpoints of the API:

| Endpoint | What it does |
|---|---|
| `GET /api/sessions` | The sessions of the working directory |
| `POST /api/sessions` | A new session |
| `GET /api/sessions/{id}` | One session |
| `GET /api/sessions/{id}/events` | The events of the session |
| `GET /api/sessions/{id}/items` | The items of the session after a sequence number |
| `GET /api/sessions/{id}/stream` | The stream of the events (SSE) |
| `GET /api/sessions/{id}/status` | The state, the model, the tokens, the cost |
| `GET /api/sessions/{id}/metrics` | The metrics of the session |
| `GET /api/sessions/{id}/changes` | The files that were changed |
| `POST /api/sessions/{id}/resume` | Continue the session |
| `POST /api/sessions/{id}/fork` | A copy of the session |
| `POST /api/sessions/{id}/messages` | Send a message |
| `POST /api/sessions/{id}/interrupt` | Interrupt the turn |
| `POST /api/sessions/{id}/mode` | Change the permission mode of the session |
| `POST /api/approvals/{id}` | Answer an approval |
| `GET /api/commands` | The slash commands |
| `GET /api/config` | The configuration and its layers |
| `PUT /api/config/model` | Write the model to the user level file |
| `GET /api/config/model/key` | The key of the endpoint |
| `PUT /api/config/permissions` | Write the permissions to the user level file |
| `POST /api/config/model/test` | One cheap call to test the model |
| `GET /api/files` | The files of the working directory |
| `GET /api/file` | One file |
| `GET /api/diff` | The diff of one file |
| `GET /api/i18n/{language}` | The strings of a language |

### When something goes wrong

| Status | Message | What it means | What to do |
|---|---|---|---|
| 403 | `the X-Coder-Client header is missing` | A write without the header. A browser on another site cannot send it. | Add `-H 'X-Coder-Client: 1'`. |
| 404 | `there is no session with the id {id}` | The id is unknown. | `GET /api/sessions` for the list. |
| 404 | `no approval is waiting for the id {id}` | The approval was answered already, or it timed out. | Nothing to do. |
| 404 | `unknown language` | The language of `/api/i18n/{language}` is not one of the ones that are on. | Use `en` or `zh`. |
| 400 | `the message is empty` | The message has no text. | Send a text. |
| 400 | `unknown permission mode '{value}'` | The mode is not one of the five. | Use `default`, `acceptEdits`, `plan`, `readonly` or `bypass`. |
| 400 | `the decision must be allow, deny or always` | The answer of an approval is wrong. | Use `allow`, `deny` or `always`. |
| 400 | `'{path}' is not a directory` | A path of the file API is a file. | Use a directory. |
| 403 | `'{path}' is outside the working directory {cwd}` | The path leaves the working directory. | Nothing — that is the boundary. |
| 409 | `the session {id} is running` | The session is busy, so it cannot be forked or resumed. | Wait for the turn to end, or interrupt it. |

The approval that nobody answered is denied after `ui.approval_timeout`
seconds, and the browser is told `timed_out: true`.

An approval of a tool that changes a file writes a rule into
`~/.coderagent/rules.yaml` — the same file the terminal uses.

The address of the server is printed on the start. With `--host 0.0.0.0` the
server warns:

```
The web interface listens on 0.0.0.0: everybody who can reach that address can drive the agent.
```

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

### Example

```bash
# A file.
coder -t "..." -c myconf.yaml
# Overrides, repeatable.
coder -t "..." -c model.model_name=deepseek/deepseek-chat -c agent.max_turns=20
```

The layers, from the lowest to the highest priority:

1. the defaults of the package (`src/coderagent/config/defaults.yaml`),
2. `.coderagent/config.yaml` of the project,
3. `~/.coderagent/config.yaml` of the user,
4. the `-c` of the command line.

The model name is looked up in this order: the `-c` of the command line, the
project file, the user file, `$MSWEA_MODEL_NAME`, and at the end
`anthropic/claude-sonnet-4-5`.

The sections and what they hold:

| Section | The keys |
|---|---|
| `model` | `model_name`, `model_kwargs`, `max_retries`, `litellm_config`, `routing`, `routing_rules`, `set_cache_control` |
| `agent` | `system_prompt`, `max_turns`, `cost_limit` |
| `tools` | `enabled`, `disabled`, `bash_timeout`, `max_output_tokens` |
| `permissions` | `mode`, `rules`, `deny_paths`, `include_dirs` |
| `context` | `context_window`, `reserved_output`, `compact_threshold`, `keep_recent_turns`, `keep_recent_token_ratio`, `compact_every_turns`, `auto_compact`, `summarize_model` |
| `memory` | `project_path`, `user_path`, `enabled` |
| `checkpoint` | `enabled`, `keep` |
| `mcp` | `servers`, `timeout` |
| `hooks` | `events` |
| `ui` | `theme`, `show_reasoning`, `approval_timeout` |
| `sandbox` | `type` and the options of the environment |

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Nothing happens, the setting is ignored | A key that does not exist is ignored, silently. | Check the spelling against the table above. |
| `yaml.scanner.ScannerError` | The YAML of a layer cannot be parsed. | Fix the YAML; the message has the line. |
| `pydantic_core.ValidationError` | A value has the wrong type — a string where a number belongs. | The message names the field. |
| `FileNotFoundError: Could not find config file for ... (tried: [...])` | `-c myconf.yml` was given, but the file that is looked for is `myconf.yaml`. | Use the name with `.yaml`, or give the full path. |
| The model is not the one in the file | A layer above the file wins. | Remember the order; `--list` of the layers is on the settings page. |
| `ui.show_reasoning` has no effect | The key exists, but nothing reads it yet. | The reasoning of the model is always shown in the terminal. |

## The commands

Twenty-four built-in commands: `/help`, `/model`, `/mode`, `/plan`,
`/compact`, `/clear`, `/resume`, `/fork`, `/rewind`, `/diff`, `/init`,
`/cost`, `/todos`, `/mcp`, `/permissions`, `/hooks`, `/agents`, `/skills`,
`/plugins`, `/memory`, `/status`, `/sandbox`, `/export` and `/context`.

Your own commands live in `.coderagent/commands/*.md` and join them.

### Example

```bash
coder -t "/cost"          # a command in the terminal
coder -t "/model deepseek/deepseek-chat"
coder -t "/mode plan"
```

A command that takes arguments is the rest of the line:

```
/model deepseek/deepseek-chat
/rewind 20261109-3f0a91
```

In the browser the commands are in the palette of the chat page, and the list
comes from `GET /api/commands`.

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `Unknown command '/foo'. Try /help.` | There is no such command. | `/help` lists them; `/help <name>` explains one. |
| `Unknown mode 'bogus'. Use one of: default, acceptEdits, plan, bypass, readonly.` | `/mode` was given a mode that does not exist. The mode of the session is unchanged. | Use one of the five. |
| `/rewind` with an id that is not a checkpoint | `ValueError: no checkpoint '<id>' in this session` | `/rewind` without an id lists the checkpoints. |
| `Not a git repository: {cwd}` | `/diff` runs `git diff`, and this directory is not a repository. | Run it in a repository, or use the changes of the web page. |
| `{path} already exists.` | `/init` does not overwrite an `AGENTS.md`. | Edit the file yourself. |
| `No sessions yet.` | `/resume` without an id found nothing in this directory. | Run a turn first. |

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

### Example

```bash
mini --model litellm/deepseek/deepseek-flash --environment docker \
  --task "the failing test is in test_api.py"

mini-extra swebench --model litellm/deepseek/deepseek-flash --workers 8 \
  --slice 0:100
```

The trajectory of a run is a JSON file with the messages, the tool calls and
the cost of every step; `inspector` reads it.

### When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| The environment cannot be built | The image is missing or the binary of the environment is not installed. | The same errors as the sandbox of the coding agent. |
| The model answers without a tool call | The model of the benchmark is a text based one, or the format of the answer is wrong. | Use a model that speaks the tool protocol, or a model class of the benchmark that wraps it. |

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
