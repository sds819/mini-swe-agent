# The commands of the coding agent

The `coder` command starts an interactive session. Everything that starts with a
slash is a command, everything else is a message for the agent.

```bash
coder                 # the terminal interface
coder --task "fix the failing test"   # one turn, then the answer
coder --task "/help"  # a command without the interface
```

## The built-in commands

| Command | What it does |
|---|---|
| `/help` | The list of the commands |
| `/model` (`/m`) | Show or switch the model |
| `/mode` | Show or switch the permission mode |
| `/plan` | Switch to plan mode, where nothing is changed |
| `/compact` | Compact the conversation now |
| `/clear` | Start a new session |
| `/resume` | List the sessions or resume one |
| `/fork` | Copy the session into a new one |
| `/rewind` | Show the checkpoints or roll back to one |
| `/diff` | Show the changes in the working tree |
| `/init` | Write an `AGENTS.md` for this project |
| `/cost` | The tokens and the money spent |
| `/todos` | The task list of the agent |
| `/mcp` | The MCP servers and their state |
| `/permissions` | The rules that are in effect |
| `/hooks` | The hooks that are loaded |
| `/status` | The state of the session |
| `/export` | Write the conversation to a file |
| `/context` | The size of the context |

## Your own commands

A command is a markdown file in `.coderagent/commands`. The file starts with a
front matter, the way Claude Code does it:

```markdown
---
description: Generate a commit message
argument-hint: [file]
allowed-tools: bash(git diff:*), read
---
Describe the change of $1.
Everything else: $ARGUMENTS
```

- `$ARGUMENTS` becomes everything the user typed after the command.
- `$1`, `$2`, … become the arguments, one by one.
- `allowed-tools` limits the tools the command may use. The tools of the
  session are back when the command is done.
- `model` picks another model for this command.

The command above is used like this:

```bash
/commit src/coderagent/core/loop.py
```

A file without a front matter is ignored. The commands of the project are found
by walking up from the working directory.
