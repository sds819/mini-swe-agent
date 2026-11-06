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

- `matcher` is a regular expression of the tool names. An empty matcher means
  every tool.
- `command` runs with the shell, in the directory of the session.
- `timeout` is in seconds. The default is 10.

## The moments

| Hook | When | What it can do |
|---|---|---|
| `SessionStart` | The session starts | Add context |
| `UserPromptSubmit` | After the prompt, before the model | Add context, or block the prompt |
| `PreToolUse` | Before the tool runs | Allow, deny, or rewrite the arguments |
| `PostToolUse` | After the tool ran | Add context, or block the result |
| `Stop` | The agent wants to stop | Send it back to work |
| `SessionEnd` | The session ends | Nothing |

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

The `PreToolUse` hook runs **before** the permission check, so the command that
is approved is the command that was rewritten.

## When a hook fails

A hook that crashes, times out or writes something that is not JSON is ignored:
the action goes on. Set `strict: true` on the hook to block the action instead.
