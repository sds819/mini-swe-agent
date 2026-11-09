# coding agent 的功能

`coder` 有什么本事，一条一条写下来。每一节最后都给出讲得更细的文档。

> English: [The features of the coding agent](coderagent_features.md)

## 怎么用

- **终端里跑一轮**——`coder -t "把失败的测试修好"`。结果按文本打印，
  加 `--output-format json` 就是 JSON。
- **终端界面**——不给任务就是 `coder`，也可以 `coder --tui`。全屏界面，
  有状态栏、工具卡片和审批。
- **浏览器里**——`coder web`。同一个 agent，一个聊天页，一个设置模型配置
  的设置页。
- **当 API 用**——浏览器做的每个动作都是普通 HTTP 调用，脚本也能驱动它。
- **当库用**——`coderagent.run.run_turn` 和 `build_loop` 把 agent 放进别的
  Python 程序里。
- **跑 benchmark**——mini-swe-agent 的那些运行脚本用同一套模型接口解
  SWE-bench 和 ProgramBench。

## 模型

- **litellm 认识的任何厂商**——OpenAI、DeepSeek、Anthropic、Gemini、
  Mistral、OpenRouter……名字前面那个厂商决定调谁：`deepseek/deepseek-flash`。
- **第三方端点**——`api_base` 里写一个 OpenAI 兼容的地址，配它自己的 key。
  地址可以直接粘完整的 `/chat/completions`，`/v1` 后面那段会被剪掉，
  因为 litellm 自己会加。
- **别名**——一个带模型列表的 litellm 配置文件。模型名可以是那个列表里的
  一条别名，端点的 key 就留在那个文件里。
- **缓存标记**——`set_cache_control: ephemeral`，给支持它的厂商用。
- **重试**——`max_retries`，默认三次。
- **按用途路由**——`main`、`cheap`、`summarize`、`reflect`、`strong` 可以
  各配一个模型。
- **按会话状态路由**——像 `tokens > 50000` 这样的规则会换模型，理由写在
  事件日志里。
- **摘要用别的模型**——`context.summarize_model`，留空就是 agent 自己那个。
- **流式输出**——答案一段一段到，终端和浏览器都是。

## 工具

十三个内置工具：

| 工具 | 干什么 |
|---|---|
| `read` | 读文件，带行号 |
| `write` | 写文件，没有就建 |
| `edit` | 替换文件里一处完全一样的字符串 |
| `multi_edit` | 一个文件里多处改动——要么全成，要么全不成 |
| `glob` | 按模式找文件（`*` 在一段里，`**` 跨目录） |
| `grep` | 用正则搜内容，可以要匹配的行、文件名或者计数 |
| `ls` | 列目录；`depth: -1` 是整棵树 |
| `bash` | 跑一条命令，可以带超时，也可以放到后台 |
| `bash_output` | 后台命令到目前为止的输出 |
| `bash_kill` | 杀掉后台命令 |
| `todo_write` | 这一轮要做的事 |
| `task` | 把一件自成一体的事交给子 agent |
| `skill` | 载入一个技能的说明 |

- **MCP 服务器的工具**——`mcp__<服务器>__<工具>`，配了的服务器都有。
- **插件的工具**——插件可以加工具、命令和 hook。
- **工具的 schema 会按预算裁剪**——工具塞不进上下文时，最不重要的先走。
  `bash` 和 `read` 永远不裁。
- **工具集可以配**——`tools.enabled` 是模型能调的工具清单，`tools.disabled`
  是单独拿掉几个。

## 权限

- **五种模式**——`default`、`acceptEdits`、`plan`、`readonly`、`bypass`。
- **模型会知道**——`plan` 和 `readonly` 下 agent 知道自己改不了东西，
  于是把看到的说出来，而不是动手。
- **规则**——`~/.coderagent/rules.yaml` 和 `.coderagent/rules.yaml` 按工具
  和模式决定放不放行。**用户级那份赢**。
- **`Always allow`**——审批卡片上的这个按钮会写一条规则，以后这个工具
  直接放行。
- **禁止的路径**——`permissions.deny_paths`，agent 不许碰的路径。
- **额外的目录**——`permissions.include_dirs`，工作目录以外、agent 仍然
  可以碰的目录。
- **三个答案**——允许、拒绝、永久允许。没人回答就是拒绝：浏览器里等
  `ui.approval_timeout` 秒（默认五分钟），终端里一直等，因为那儿坐着人。
- **终端里用方向键选答案**，浏览器里点卡片上的按钮；没有终端时一律拒绝。
- **hook 跑在权限检查前面**——hook 可以改写这次调用或者拦下来，权限检查
  看到的是改写之后的那次。

## 会话

- **新建、列出、续接、复制**——`--resume`、`--continue`、`--fork`、`--list`。
- **事件日志是唯一的事实**——每条消息、每次工具调用、每个结果、每笔钱都
  追加进一个 JSONL 文件。会话靠重放它重建。
- **检查点**——每次写文件之前存一份快照，`/rewind` 能退回去。
- **`/clear`**——开一个新会话，旧的留在日志里。
- **花了多少钱**——每个会话的 token 和花费，在状态栏、在 `/cost`、在
  追踪文件里。
- **追踪**——`coder export --format json|otel` 把会话导出来，给看板或者
  OpenTelemetry 用。

## 上下文

- **token 是数出来的**——装了 tiktoken 就精确数，没装就估。
- **窗口跟着模型走**——DeepSeek 64k、Claude 200k、GPT 128k 这样。配置文件
  里写了 `context_window` 就以它为准。
- **自动压缩**——对话到窗口的 80 % 就做摘要、把历史缩短。摘要是结构化的：
  目标、发现、决定、动过的文件、没解决的问题、下一步、见过的错。
- **留什么**——最近几轮，或者最近 40 % 的 token，哪个多留哪个。
- **`/compact`**——随时手动压缩。
- **消息的顺序**——系统提示词、指令文件、todo、会话摘要，然后是历史。

## 记忆

- **项目记忆**——`.coderagent/memory`，一轮结束时把关于项目的东西写下来。
- **用户记忆**——`~/.coderagent/CLAUDE.md`，记用户的偏好。
- **偏好要等人确认**——先落在 `pending-memory.md`，`/memory confirm` 才写
  进去。
- **指令文件**——项目的 `AGENTS.md` 和 `CLAUDE.md`、用户的 `CLAUDE.md`，
  agent 都读。
- **可以关掉**——`memory.enabled`。

## 扩展

- **子 agent**——`.coderagent/agents/*.md`：名字、说明、系统提示词、工具
  清单、最大轮数。`code-explorer`、`verifier`、`refactorer` 是自带的。
  模型看得见它们的索引，能直接按名字调。
- **技能**——`.coderagent/skills/<名字>/SKILL.md`：某类任务的步骤、脚本和
  模板。合适的时候 agent 自己会载入。
- **插件**——`.coderagent/plugins`：一个 Python 模块，能加工具、命令和
  hook。第一次用要信任一次。
- **hook**——六个时机：`SessionStart`、`UserPromptSubmit`、`PreToolUse`、
  `PostToolUse`、`Stop`、`SessionEnd`。hook 是一条命令，读 JSON 答 JSON：
  允许、拒绝、拦下来，带理由、带额外上下文，或者带改写过的参数。
- **自己的命令**——`.coderagent/commands/*.md`：一个 slash 命令，带说明、
  参数提示、能用的工具，还有自己的模型。
- **MCP 服务器**——stdio 或者 http。它们的工具和别的工具一样，工具名是
  `mcp__<服务器>__<工具>`，一样要审批，断了会自己重连。

## 沙箱

- **默认是本机**——命令就在工作目录里跑。
- **也可以是容器**——`docker`、`singularity`、`bubblewrap`、`contree`，
  还有 SWE-rex 的远程沙箱。和 mini-swe-agent 用的是同一批环境。
- **只有 `bash` 进沙箱**——文件工具还在工作目录里。
- **`/sandbox`**——告诉你命令在哪里跑。

## 终端界面

- **答案是流式出来的**——正文和思考过程都是。
- **状态栏**——模型、token、花费、目录、权限模式。
- **工具卡片**——这次调用、输出、以及这次改动的 diff。
- **审批**——`y`、`n`、`a`，或者方向键在带编号的列表上选。
- **长输出折起来**——有意思的那部分留在眼前。
- **todo 面板**——这一轮要做的事。

## 网页版

- **聊天页**——三栏：左边是会话和文件，中间是对话，右边是状态、改动和
  文件。
- **答案是流式到的**——走 SSE，中途才打开页面的浏览器看到的是整段回答。
- **设置页**——模型写成表单，每个字段下面写着它来自哪一层，底下的表格
  列出所有层，密钥都被抹掉。
- **测一下连接**——发一次最便宜的调用，顺带告诉模型会不会调工具。
- **测一个模型**——一块独立的面板：端点、key、模型名，不写任何文件。
- **权限在两个地方**——设置页管下一个会话，聊天页管当前这个会话，立刻生效。
- **浏览器里也有审批**——同样三个答案。
- **语言**——英文和中文。顶栏的下拉框换语言时整个页面当场换掉，不刷新，
  选择记在浏览器和 cookie 里；访客没选过的时候由地址所在的地区决定。
- **安全模型**——没有认证，默认只听 `127.0.0.1`，写接口要一个跨站请求
  发不出来的头，路径出不了工作目录，key 只在你要的时候才露面。

## 配置

- **四层**——包里的默认值、项目文件 `.coderagent/config.yaml`、用户文件
  `~/.coderagent/config.yaml`、命令行的覆盖（`-c key=value`）。后面的赢。
- **有哪些段**——`model`、`agent`、`tools`、`permissions`、`context`、
  `memory`、`checkpoint`、`mcp`、`hooks`、`ui`、`sandbox`。
- **路径**——`MSWEA_CODER_HOME` 可以把用户级文件挪到别处。
- **设置页只写用户级文件**——项目级那份在仓库里，永远不写。

## 命令

二十四个内置命令：`/help`、`/model`、`/mode`、`/plan`、`/compact`、
`/clear`、`/resume`、`/fork`、`/rewind`、`/diff`、`/init`、`/cost`、
`/todos`、`/mcp`、`/permissions`、`/hooks`、`/agents`、`/skills`、
`/plugins`、`/memory`、`/status`、`/sandbox`、`/export`、`/context`。

自己的命令放在 `.coderagent/commands/*.md`，和它们一起用。

## mini-swe-agent 的 benchmark 那部分

- **`mini`**——一个运行脚本：任务、模型、环境，外加一个轨迹文件。
- **SWE-bench**——整个数据集，能并行，能切片能过滤。
- **SWE-bench 单个实例**——一道题。
- **ProgramBench**——编程 benchmark。
- **Inspector**——读轨迹文件，看 agent 干了什么。
- **环境**——local、docker、singularity、bubblewrap、contree、SWE-rex 的
  docker 和 modal。
- **模型**——litellm 覆盖大多数厂商，另外还有 portkey、openrouter、
  requesty、基于文本的模型和 roulette 模型。

## 细节在哪

| 文档 | 里面有什么 |
|---|---|
| [coding agent 概览](coderagent.md) | 从第一次会话到所有文件，全套 |
| [命令](coderagent_commands.md) | 每个命令，以及自己的命令 |
| [网页版](coderagent_web_zh.md) | 聊天页、设置页、API |
| [子 agent](coderagent_subagents.md) | 怎么写一个子 agent |
| [技能](coderagent_skills.md) | 怎么写一个技能 |
| [hook](coderagent_hooks.md) | 六个时机和 hook 的回答 |
| [插件](coderagent_plugins.md) | 怎么写一个插件 |
| [MCP 服务器](coderagent_mcp.md) | 服务器怎么配 |
| [记忆](coderagent_memory.md) | 那些文件和确认 |
| [模型路由](coderagent_routing.md) | 用途和规则 |
| [沙箱](coderagent_sandbox.md) | 那些环境 |
| [追踪导出](coderagent_export.md) | 一个会话的追踪 |
| [快速开始](coderagent_quickstart.md) | 头十分钟 |
