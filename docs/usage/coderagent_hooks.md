# Hooks

A hook is a command of the user that runs at an important moment of a session.
A hook can block an action, rewrite its arguments or add something to the
context of the model.

## The configuration

```yaml
hooks:
  events:
    PreToolUse:
      - matcher: "bash"
        hooks:
          - type: command
            command: ./scripts/guard.sh
            timeout: 10
    PostToolUse:
      - matcher: "edit|write"
        hooks:
          - type: command
            command: ruff format {file}
```

| Key | What it is | Default |
|---|---|---|
| `matcher` | A regular expression of the tool names. Empty means every tool | |
| `command` | The command to run, with the shell, in the directory of the session | |
| `timeout` | How long it may take, in seconds | 10 |
| `strict` | When the hook fails, block the action instead of letting it through | false |

The hooks of the project live in `.coderagent/config.yaml`, the hooks of the
user in `~/.coderagent/config.yaml`. A plugin may bring hooks too.

The matcher is matched against the name of the tool, so it only means
something for `PreToolUse` and `PostToolUse`. Leave it empty for the other
events.

## The moments

| Hook | When | What it can do |
|---|---|---|
| `SessionStart` | The session starts | Nothing. It is a notification |
| `UserPromptSubmit` | After the prompt, before the model | Add context, or block the prompt |
| `PreToolUse` | Before the tool runs | Allow, deny, or rewrite the arguments |
| `PostToolUse` | After the tool ran | Add context, or block the result |
| `Stop` | The agent wants to stop | Send it back to work |
| `SessionEnd` | The session ends | Nothing. It is a notification |

Each event has its own payload:

| Hook | What it reads |
|---|---|
| `SessionStart` | `session_id`, `cwd` |
| `UserPromptSubmit` | `prompt` |
| `PreToolUse` | `tool`, `params` |
| `PostToolUse` | `tool`, `params`, `result` |
| `Stop` | `last_message` |
| `SessionEnd` | `session_id`, `turns`, `cost` |

## What a hook answers

The hook reads the details on its standard input and writes its answer as JSON
on its standard output:

```python
#!/usr/bin/env python3
import json
import sys

payload = json.load(sys.stdin)
if payload.get("tool") == "bash" and "rm -rf" in payload["params"].get("command", ""):
    print(json.dumps({"decision": "deny", "reason": "that command is not allowed"}))
```

The keys are:

- `decision`: `allow`, `deny` or `block`.
- `reason`: why. It goes back to the model as the error of the tool.
- `additionalContext`: something for the model to read.
- `updatedInput`: the arguments the tool gets instead of the ones of the model.

Nothing on the standard output means the hook has no opinion. The output of
several hooks is put together: a `deny` wins over everything, the contexts are
concatenated and the last `updatedInput` wins.

## What the answer does

| The answer | What happens |
|---|---|
| `PreToolUse` denies | The tool call fails, the reason goes back to the model |
| `PreToolUse` rewrites the arguments | The tool runs with the new arguments |
| `PostToolUse` denies | The result of the tool becomes an error |
| `PostToolUse` adds context | The context is appended to the result of the tool |
| `UserPromptSubmit` denies | The turn ends with an error, the model is not called |
| `UserPromptSubmit` adds context | The context is appended to the prompt |
| `Stop` denies | The agent goes on, the reason is a new message for it |

The `PreToolUse` hook runs **before** the permission check, so the command
that is approved is the command that was rewritten.

## When a hook fails

A hook that crashes, times out or writes something that is not JSON is ignored:
the action goes on.

`strict: true` changes one thing: a hook that ends with a non-zero exit code
denies the action, and its standard error is the reason. A timeout and a
broken answer are ignored either way.
