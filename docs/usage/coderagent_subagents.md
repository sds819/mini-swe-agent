# Sub agents

> 中文版：[子 agent](coderagent_subagents_zh.md)

A sub agent is a job that runs in its own context and returns a conclusion.

The main agent reads the code, but a job like "find every place this pattern
occurs" fills the context with output that nobody reads again. A sub agent does
that job in a context of its own, and the main agent gets the conclusion:

```
main agent calls `task`
  → the sub agent gets its own system prompt and its own prompt
  → the sub agent works with a white list of tools
  → the sub agent ends
  → the main agent gets the conclusion, not the whole story
```

The sub agent cannot see the conversation of the main agent. Whatever it needs
has to be in the `prompt` of the call.

## The three that are always there

| Name | What it does | Tools | Purpose | Turns |
|---|---|---|---|---|
| `code-explorer` | Find code: locate a symbol, follow a call chain | `read` `grep` `glob` `ls` | cheap | 15 |
| `verifier` | Check a result on its own: run the tests, reproduce the bug | `read` `grep` `glob` `bash` | main | 20 |
| `refactorer` | Change the same pattern everywhere | `read` `edit` `grep` `glob` | main | 30 |

`/agents` lists them, with the tools of each one:

```
code-explorer   cheap   read, grep, glob, ls
                Find code: locate a symbol, follow a call chain, explain how a part works.
```

## Writing your own

A sub agent is a markdown file. The front matter says what it is, the body is
its system prompt:

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

| Field | What it is | Default |
|---|---|---|
| `name` | The name of the sub agent | The name of the file |
| `description` | What it is for. The main agent reads this one | |
| `tools` | The tools it may call. A list, or a comma separated string | `read` `grep` `glob` `bash` |
| `model_purpose` | Which model answers for it | `cheap` |
| `max_turns` | How many model calls it may make | 20 |

The tools are a white list: the sub agent cannot reach anything that is not on
it. A file without a front matter is ignored.

## Where a sub agent is looked for

| Where | What |
|---|---|
| `.coderagent/agents/*.md` | The sub agents of the project |
| `~/.coderagent/agents/*.md` | The sub agents of the user |

The project comes last, so a project may replace a sub agent of the user with
the same name. `MSWEA_CODER_HOME` moves the directory of the user.

## The result

The `task` tool returns a JSON object:

```json
{
  "status": "completed",
  "summary": "The parser lives in src/parser.py and is called by the CLI.",
  "findings": ["src/parser.py:42 parses the arguments"],
  "files_touched": [],
  "cost": 0.031,
  "turns": 7,
  "purpose": "cheap"
}
```

| Field | What it is |
|---|---|
| `status` | `completed`, `max_turns` or `error` |
| `summary` | The last thing the sub agent said. This is the conclusion |
| `findings` | The bullet points of that conclusion |
| `files_touched` | The files it **changed**. The files it read are not in it |
| `cost` | What it spent |
| `turns` | How many model calls it made |
| `purpose` | The purpose of the model that answered for it |

`status` is `max_turns` when the sub agent ran out of turns before it was
done, and `error` when its model failed. An `error` comes back to the main
agent as a failed call, so it knows the answer is not trustworthy.

The money of the sub agent is the money of the session: it is part of the bill
of the session, and of `cost_limit`. When the sub agent runs on its own model
(`model_purpose` is routed to a different model), its cost is booked on the
main model, so the budget of the session still holds it.

## The permissions

The tools of the sub agent go through the same permission layer as the tools
of the main agent. In `plan` mode a sub agent cannot write either.

The `task` tool itself is a tool that is asked for, like `bash`. Without a
terminal nobody can answer, so in a script the call is refused:

```bash
coder --task "..." --permission-mode bypass
```

or a rule of your own:

```yaml
# .coderagent/rules.yaml
rules:
  - tool: task
    pattern: "*"
    decision: allow
```
