# 命令

`coder` 命令起一个交互式会话。以斜杠开头的是命令，其余都是给 agent 的消息。

```bash
coder                 # 终端界面
coder --task "把失败的测试修好"   # 跑一轮，然后是答案
coder --task "/help"  # 不进界面，直接跑一个命令
```

> 英文版：[The commands of the coding agent](coderagent_commands.md)

## 内置命令

| 命令 | 干什么 |
|---|---|
| `/help` | 命令的列表 |
| `/model`（`/m`） | 看或者换模型 |
| `/mode` | 看或者换权限模式 |
| `/plan` | 切到 plan 模式，什么都不改 |
| `/compact` | 现在就压缩对话 |
| `/clear` | 开一个新会话 |
| `/resume` | 列出会话，或者续接一个 |
| `/fork` | 把会话复制成一个新会话 |
| `/rewind` | 列出检查点，或者退回去一个 |
| `/diff` | 看工作区里的改动 |
| `/init` | 给这个项目写一个 `AGENTS.md` |
| `/cost` | 已经花掉的 token 和钱 |
| `/todos` | agent 的任务清单 |
| `/mcp` | MCP 服务器和它们的状态 |
| `/permissions` | 现在生效的规则 |
| `/hooks` | 加载了的 hook |
| `/agents` | 可以用的子 agent |
| `/skills` | 可以用的技能 |
| `/plugins` | 插件，或者信任其中一个 |
| `/memory` | 项目的记忆和用户的记忆 |
| `/status` | 会话的状态 |
| `/sandbox` | agent 的命令在哪里跑 |
| `/export` | 把对话写成文件 |
| `/context` | 上下文有多大 |
| `/exit`（`/quit`） | 退出界面 |

`/cost` 里的钱就是会话的钱。新会话（`/clear`）从零开始，不管上一个会话花了
多少。

`/exit` 关掉终端界面，和 `ctrl+q` 一样。浏览器里没有东西可关，所以它会说
服务还在跑：要停掉它，得在启动它的那个终端里按 `ctrl+c`。

## 自己的命令

一个命令就是 `.coderagent/commands` 里的一个 markdown 文件。文件开头是 front
matter，和 Claude Code 一个写法：

```markdown
---
description: Generate a commit message
argument-hint: [file]
allowed-tools: bash(git diff:*), read
---
Describe the change of $1.
Everything else: $ARGUMENTS
```

- `$ARGUMENTS` 变成用户敲在命令后面的全部内容。
- `$1`、`$2`…… 变成参数，一个一个来。
- `allowed-tools` 限定这个命令能用的工具。命令干完，session 的工具就回来了。
- `model` 给这个命令换一个模型。

上面那个命令这么用：

```bash
/commit src/coderagent/core/loop.py
```

没有 front matter 的文件会被忽略。命令只在 `<cwd>/.coderagent/commands/*.md`
里找——agent 不会一层层往上找。
