# 子 agent

子 agent 是一件在自己的上下文里干完、然后交回一个结论的活。

主 agent 读代码，但像「找出这个模式出现的所有地方」这种活会把上下文塞满没人再看
一遍的输出。子 agent 在自己的上下文里干这件事，主 agent 拿到的是结论：

```
主 agent 调用 `task`
  → 子 agent 拿到自己的系统提示词和自己的 prompt
  → 子 agent 用一份工具白名单干活
  → 子 agent 结束
  → 主 agent 拿到结论，不是整个过程
```

子 agent 看不见主 agent 的对话。它需要什么，都得写在这次调用的 `prompt` 里。

> 英文版：[Sub agents](coderagent_subagents.md)

## 自带的三个

| 名字 | 干什么 | 工具 | 用途 | 轮数 |
|---|---|---|---|---|
| `code-explorer` | 找代码：定位一个符号，追一条调用链 | `read` `grep` `glob` `ls` | cheap | 15 |
| `verifier` | 自己验一遍结果：跑测试，复现 bug | `read` `grep` `glob` `bash` | main | 20 |
| `refactorer` | 把同一个模式改到所有该改的地方 | `read` `edit` `grep` `glob` | main | 30 |

`/agents` 会列出它们，还有每个的工具：

```
code-explorer   cheap   read, grep, glob, ls
                Find code: locate a symbol, follow a call chain, explain how a part works.
```

## 自己写一个

子 agent 是一个 markdown 文件。front matter 说明它是什么，正文是它的系统提示词：

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

| 字段 | 是什么 | 默认值 |
|---|---|---|
| `name` | 子 agent 的名字 | 文件名 |
| `description` | 它干什么用。主 agent 读的是这一条 | |
| `tools` | 它能调的工具。一个列表，或者逗号隔开的字符串 | `read` `grep` `glob` `bash` |
| `model_purpose` | 用哪个模型替它回答 | `cheap` |
| `max_turns` | 它最多能调几次模型 | 20 |

工具是**白名单**：白名单上没有的，子 agent 够不着。没有 front matter 的文件会被
忽略。

## 子 agent 在哪里找

| 哪里 | 什么 |
|---|---|
| `.coderagent/agents/*.md` | 项目的子 agent |
| `~/.coderagent/agents/*.md` | 用户的子 agent |

项目排在后面，所以项目可以用同名的东西盖掉用户的那个。`MSWEA_CODER_HOME`
可以挪走用户的那个目录。

## 结果

`task` 工具返回一个 JSON 对象：

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

| 字段 | 是什么 |
|---|---|
| `status` | `completed`、`max_turns` 或者 `error` |
| `summary` | 子 agent 最后说的话。这就是结论 |
| `findings` | 这个结论里的要点 |
| `files_touched` | 它**改过**的文件。读过的文件不在里面 |
| `cost` | 它花的钱 |
| `turns` | 它调了几次模型 |
| `purpose` | 替它回答的模型是哪个用途 |

轮数用完了、活还没干完时 `status` 是 `max_turns`；它的模型挂了时是 `error`。
`error` 会作为一次失败的调用回到主 agent，主 agent 就知道这个答案不可信。

子 agent 的钱是会话的钱：它算在这个会话的账单里，也算在 `cost_limit` 里。
当子 agent 跑在自己的模型上（`model_purpose` 被路由到别的模型），它的花费记在
主模型上，所以会话的预算照样管得住它。

## 权限

子 agent 的工具和主 agent 的工具走同一层权限。在 `plan` 模式下，子 agent 同样
不能写东西。

`task` 工具本身是个要问的工具，和 `bash` 一样。没有终端就没人能回答，所以脚本
里这次调用会被拒：

```bash
coder --task "..." --permission-mode bypass
```

或者自己写一条规则：

```yaml
# .coderagent/rules.yaml
rules:
  - tool: task
    pattern: "*"
    decision: allow
```
