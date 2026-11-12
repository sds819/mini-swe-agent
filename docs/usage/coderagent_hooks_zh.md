# Hooks

hook 是用户自己写的命令，在会话的关键时刻跑一次。它可以拦住一次操作、改写它的参数，或者给模型补一点上下文。

> 英文版：[Hooks](coderagent_hooks.md)

## 配置

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

| 键 | 是什么 | 默认值 |
|---|---|---|
| `matcher` | 工具名的正则。空表示所有工具 | |
| `command` | 要跑的命令，用 shell 跑，在会话的目录里 | |
| `timeout` | 最多跑多久，单位是秒 | 10 |
| `strict` | hook 失败时拦住这次操作，而不是放行 | false |

项目的 hook 写在 `.coderagent/config.yaml`，用户的 hook 写在 `~/.coderagent/config.yaml`。插件也可以带 hook。
两个文件像其它配置一样合并：事件是合并的，但同一个事件下 hook 的那份列表会被用户那份整个换掉。

`matcher` 是拿工具名去匹配的，所以它只对 `PreToolUse` 和 `PostToolUse` 有意义。其它事件留空就行。

## 六个时刻

| Hook | 什么时候 | 能做什么 |
|---|---|---|
| `SessionStart` | 会话开始 | 什么也不做，是个通知 |
| `UserPromptSubmit` | 拿到提问之后、问模型之前 | 补上下文、改写提问，或者拦住提问 |
| `PreToolUse` | 工具跑之前 | 允许、拒绝，或者改写参数 |
| `PostToolUse` | 工具跑完之后 | 补上下文，或者把结果拦下来 |
| `Stop` | agent 想停下来 | 让它回去接着干 |
| `SessionEnd` | 这一轮结束 | 什么也不做，是个通知 |

`SessionEnd` 是每一轮结束时都跑，不是只在整个会话结束时。

每个事件读到的内容不一样：

| Hook | 读到什么 |
|---|---|
| `SessionStart` | `session_id`、`cwd` |
| `UserPromptSubmit` | `prompt` |
| `PreToolUse` | `tool`、`params` |
| `PostToolUse` | `tool`、`params`、`result` |
| `Stop` | `last_message` |
| `SessionEnd` | `session_id`、`turns`、`cost` |

## hook 怎么回答

hook 从标准输入读这些细节，把答案写成 JSON 写到标准输出：

```python
#!/usr/bin/env python3
import json
import sys

payload = json.load(sys.stdin)
if payload.get("tool") == "bash" and "rm -rf" in payload["params"].get("command", ""):
    print(json.dumps({"decision": "deny", "reason": "that command is not allowed"}))
```

可以写的键：

- `decision`：`allow`、`deny` 或 `block`。
- `reason`：为什么。它会作为工具的错误回到模型那里。
- `additionalContext`：给模型看的一句话。
- `updatedInput`：这一刻的新输入。`PreToolUse` 里它是一个映射，替换掉工具的参数；
  `UserPromptSubmit` 里它是一个字符串，替换掉用户的提问。`PostToolUse` 里工具已经跑完了，
  给映射也换不了什么。

标准输出是空的，意思就是这个 hook 没有意见。几个 hook 的答案会合并起来：`deny`
压过其他一切，上下文拼在一起，`updatedInput` 取最后一个。

## 答案会做什么

| 答案 | 会发生什么 |
|---|---|
| `PreToolUse` 拒绝 | 这次工具调用失败，理由回到模型那里 |
| `PreToolUse` 改写参数 | 工具用新的参数跑 |
| `PostToolUse` 拒绝 | 回给模型的那条消息变成一个错误，日志里工具的结果照旧 |
| `PostToolUse` 补上下文 | 上下文追加到工具的结果后面 |
| `UserPromptSubmit` 拒绝 | 这一轮以错误结束，模型根本不被调用 |
| `UserPromptSubmit` 补上下文 | 上下文追加到提问后面 |
| `UserPromptSubmit` 改写提问 | 模型看到的是新提问，日志里两个都留着 |
| `Stop` 拒绝 | agent 接着干，理由作为一条新消息给它（每轮最多三次） |

`PreToolUse` 的 hook 跑在**权限检查之前**，所以被批准的是被改写之后的那条命令。

## 一个改写提问的 hook

```python
#!/usr/bin/env python3
import json
import sys

payload = json.load(sys.stdin)
print(json.dumps({"updatedInput": payload["prompt"] + "\n\n用中文回答。"}))
```

模型从头到尾看不到用户原话，只看到改写后的那份。事件日志里存的是**模型看到的那份**，
这样重放这个会话时说的一样的话；用户原话放在同一条记录的 `original` 里。网页版里，
气泡显示用户写的话，下面一行小字说明给 agent 的是什么。

`PreToolUse` 的 hook 如果回答一个字符串 `updatedInput`，什么也不会发生：只有映射
才能替换工具的参数。

## hook 失败的时候

hook 崩了、超时了，或者写出来的东西不是 JSON，都会被忽略：操作照旧进行。

`strict: true` 只改一件事：以非零退出码结束的 hook 会拦住这次操作，它的标准错误
就是理由。超时和坏掉的答案两种情况下都被忽略。
