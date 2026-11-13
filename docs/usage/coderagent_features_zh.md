# coding agent 的功能

`coder` 有什么本事，一条一条写下来。每一节最后都给出讲得更细的文档，每一节
都有用法例子和出错时怎么办。

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

### 用法例子

```bash
# 跑一轮，答案是文本。
coder -t "给 src/app.py 加个 docstring"

# 跑一轮，答案是 JSON（给脚本用）。
coder -t "列一下这个目录里的文件" --output-format json

# 终端界面。
coder                      # 在终端里这就是 TUI
coder --tui                # 明确写出来

# 浏览器。
coder web --cwd . --port 8765

# 这个目录的会话，最新的在前。
coder --list
```

一轮的 JSON 有这些字段：`session_id`、`messages`、`cost`、`session_cost`、
`stop_reason`、`error`。

```json
{
  "session_id": "20261109-3f0a91",
  "messages": [{"role": "assistant", "content": "我把 docstring 加上了。"}],
  "cost": 0.0012,
  "session_cost": 0.0143,
  "stop_reason": "end_turn",
  "error": ""
}
```

`cost` 是这一轮花了多少，`session_cost` 是整个会话到目前为止花了多少。

`stop_reason` 是 `end_turn`、`max_turns`、`cost_exceeded`、`token_limit`、`verify_failed`、`error`、
`interrupted` 之一。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `no task given` | 没有 `-t`，也没有 `--tui`，而且 stdin 不是终端（脚本、管道）。 | 给个任务：`coder -t "..."`。 |
| `session 20261109-3f0a91` | 同上，但找到了可以续上的会话。 | 一样，加上 `-t` 就在里面跑一轮。 |
| `Unknown command '/foo'. Try /help.` | 这一行以 `/` 开头，但没有这个命令。 | 检查拼写，或者 `/help` 看列表。 |
| `ValueError: 'bogus' is not a valid PermissionMode` | `--permission-mode bogus`——这个值在建立权限策略时才检查，异常没有被捕获。 | 用 `default`、`acceptEdits`、`plan`、`readonly`、`bypass` 之一。 |
| `ValueError: Unknown output format: xml` | `--output-format` 只认 `text` 和 `json`。 | 用 `text` 或 `json`。 |
| `Unknown format 'xml'. Use json or otel.` | `coder export --format` 只认 `json` 和 `otel`。 | 用 `json` 或 `otel`。 |
| `no sessions yet` | `--list` 在这个目录里没找到会话。 | 不用管，先跑一轮。 |
| stderr 上的 `coder web: cannot listen on 127.0.0.1:8765 (Address already in use).`，退出码 1 | 端口被占。服务启动前自己先探一下，因为 uvicorn 自己的报错不告诉你该怎么办。 | 换一个端口：`coder web --port 8766`。 |

正常跑完一轮 `coder` 的退出码是 `0`，不管答案是什么；连启动都没成功时
（标志的值不对、端口被占）是 `1`。

## 模型

- **litellm 认识的任何厂商**——OpenAI、DeepSeek、Anthropic、Gemini、
  Mistral、OpenRouter……名字前面那个厂商决定调谁：`deepseek/deepseek-flash`。
- **第三方端点**——`api_base` 里写一个 OpenAI 兼容的地址，配它自己的 key。
  地址可以直接粘完整的 `/chat/completions`，`/v1` 后面那段会被剪掉，
  因为 litellm 自己会加。
- **别名**——一个带模型列表的 litellm 配置文件。模型名可以是那个列表里的
  一条别名，端点的 key 就留在那个文件里。
- **缓存标记**——`set_cache_control: default_end`，给支持它的厂商用。别的值会被拒。
- **重试**——`max_retries`，默认三次。
- **按用途路由**——`main`、`cheap`、`summarize`、`reflect`、`strong` 可以
  各配一个模型。
- **按会话状态路由**——像 `tokens > 50000` 这样的规则会换模型，理由写在
  事件日志里。
- **摘要用别的模型**——`context.summarize_model`，留空就是 agent 自己那个。
- **流式输出**——答案一段一段到，终端和浏览器都是。

### 用法例子

```bash
# 厂商就是斜杠前面那段。
coder -t "..." -m deepseek/deepseek-flash

# 一个说 OpenAI 协议的第三方端点。
coder -t "..." -m openai/MiniMax-M2.7 \
  -c model.model_kwargs.api_base=https://api.example.com/v1 \
  -c model.model_kwargs.api_key=sk-...
```

```yaml
# .coderagent/config.yaml
model:
  model_name: deepseek/deepseek-flash
  set_cache_control: default_end
  routing:
    main: deepseek/deepseek-chat
    cheap: deepseek/deepseek-flash
    summarize: deepseek/deepseek-flash
  routing_rules:
    - when: "tokens > 50000"
      purpose: strong
```

一轮用哪个模型，按这个顺序定：

1. 用户用 `/model` 选的模型（它压过所有别的东西），
2. 第一条成立的 `routing_rules`，
3. 自动策略：预算快用完了 → `cheap`，上下文太大（超过 50000 token）或
   会话太长（超过 30 轮）→ `strong`，
4. `routing.main`，没有它就是 agent 自己的模型。

换了模型，事件日志里会写理由：

```
Switched from deepseek/deepseek-flash to deepseek/deepseek-chat: the context has grown
```

理由有这些：`the budget is nearly used up`、`the context has grown`、
`the session has many turns`、`the rule '<when>' holds`、
`the rules of the routing say so`。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `LLM Provider NOT provided` | 模型名前面没有厂商。 | OpenAI 兼容的端点写 `openai/<名字>`，或者 `deepseek/<名字>`。 |
| `ValueError: Invalid mode: {mode}` | `set_cache_control` 既不是 `default_end`，也不是空的。 | 用 `default_end`，或者删掉这一行。 |
| `the file does not exist` | `model.litellm_config` 指的文件不在。 | 改路径，它是相对于工作目录的。 |
| `the file is not valid YAML: {error}` | 别名文件解析不了。 | 修 YAML。 |
| `the file has no model_list` | 别名文件里没有 `model_list`。 | 加上模型列表和它们的 `litellm_params`。 |
| `'{name}' is not one of the aliases of this file` | 模型名不在这个文件的 `model_list` 里。 | 用列表里的别名，或者去掉 `litellm_config`。 |
| `BadRequestError` | 厂商拒绝了请求（key 不对、名字不对、参数不对）。 | **不会**重试，厂商的报错就是答案。 |
| `AuthenticationError` | key 缺了或者不对。 | 设 `model.model_kwargs.api_key`，或者在别名文件里写端点的 key，或者在环境里放厂商的 key（`openai/…` 找 `OPENAI_API_KEY`）。 |
| `ContextWindowExceededError` | 请求比模型的窗口大。 | 调小 `context.context_window`，或者换一个窗口更大的模型。 |

重试和上面的错误是两回事：限流和超时才重试，坏请求不重试。重试次数来自
`MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT`，默认是 **10**。`coder web` 会用
`model.max_retries`（默认 3）去设这个变量，所以在浏览器里重试次数跟着配置
走，在终端里不跟。

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
- **工具的 schema 会按预算裁剪**——工具的 schema 最多占上下文的十分之一（`tools.schema_budget_tokens` 可以另设预算）；塞不下时最不重要的先走。
  `bash` 和 `read` 永远不裁。
- **工具集可以配**——`tools.enabled` 是模型能调的工具清单，`tools.disabled`
  是单独拿掉几个。

### 用法例子

模型会调这些工具，你也可以自己调来试：

```json
{"tool": "read", "params": {"path": "src/app.py"}}
{"tool": "edit", "params": {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 2"}}
{"tool": "grep", "params": {"pattern": "def main", "output_mode": "files_with_matches"}}
{"tool": "glob", "params": {"pattern": "src/**/*.py"}}
{"tool": "ls", "params": {"path": "src", "depth": -1}}
{"tool": "bash", "params": {"command": "pytest -q", "timeout": 300}}
{"tool": "bash", "params": {"command": "pytest -q", "run_in_background": true}}
{"tool": "bash_output", "params": {"task_id": "b7f3"}}
```

`multi_edit` 收一个列表，要么全成要么全不成：

```json
{"tool": "multi_edit", "params": {"path": "src/app.py", "edits": [
  {"old_string": "import os", "new_string": "import os\nimport sys"},
  {"old_string": "def main():", "new_string": "def main(argv=None):"}
]}}
```

`grep` 有三种模式：`content`（默认）、`files_with_matches`、`count`。
它最多返回 100 条匹配，`glob` 最多 200 个文件。

### 出错时怎么办

每个工具都不抛异常，而是回答一行 `Error: ...`，模型看得见这句话，可以自己
改。消息长这样：

| 工具 | 消息 |
|---|---|
| `read` | `Error: file not found: {path}. Use \`ls\` to see what is in that directory.` |
| `read` | `Error: '{name}' is a directory. Use \`ls\` to list it.` |
| `read` | `Error: '{name}' is a binary file.` |
| `edit` | `Error: old_string not found in {path}. Use \`read\` to see the exact content, then retry with more context.` |
| `edit` | `Error: old_string is not unique in {path}: it appears {count} times (lines {...}). Include more surrounding context to make it unique, or set replace_all=true.` |
| `multi_edit` | `Error: Edit #1 failed, no changes were written. {inner}`——文件一个字节都没动。 |
| `grep` | `Error: invalid regular expression '{pattern}': {error}` |
| `grep` | `Error: \`output_mode\` must be one of content, files_with_matches, count (got '{mode}').` |
| `glob`/`grep`/`ls` | `Error: path not found: {path}.` / `Error: not a directory: {path}.` |
| `bash` | `Error: \`command\` is required and must be a non-empty string.` |
| `bash_output` | `Error: unknown task id '{id}'.` |
| `todo_write` | `Error: todo #1 has invalid status '{status}'. Use one of pending, in_progress, completed.` |
| `task` | `Error: unknown sub agent '{name}'. Available sub agents: {...}.` |
| `skill` | `Error: unknown skill '{name}'. Available skills: {...}.` |

执行器自己的错误写在调用的结果里：

| 消息 | 什么意思 |
|---|---|
| `Error: unknown tool '{name}'. Available tools: {...}.` | 模型调了一个没注册的工具——通常是 `tools.enabled` 被收窄了。 |
| `Error: permission denied for '{tool}'. {reason}` | 规则或者模式拒绝了这次调用。 |
| `Error: the user denied '{tool}'.` | 有人在审批那里按了 `n`。 |
| `Error: '{tool}' needs approval but no approver is available. Run with --permission-mode bypass to allow it.` | 这次调用需要审批，但是没有终端可以问。`--permission-mode bypass`，或者一条允许它的规则。 |
| `Error: the hook blocked '{tool}'. {reason}` | `PreToolUse` 的 hook 拒绝了这次调用。 |
| `Error: '{tool}' failed: {type}: {e}` | 工具自己抛了异常。 |

`bash` 的退出码不是零**不算错误**：退出码是输出的一部分，写成
`[exit code 1]`。命令跑得比 `tools.bash_timeout`（默认 120 秒）久，会失败
成：

```
An error occurred while executing the command: Command 'sleep 60' timed out after 120 seconds
```

放到后台的命令回答 `Started background task {id}: {cmd}`，用 `bash_output`
读，用 `bash_kill` 杀。

工具的输出会写进会话日志，也会发给模型。里面长得像密钥的东西——API key、
token、密码、私钥——在写和发之前都会换成 `[redacted]`。带密钥的文件存进
checkpoint 时会被去掉密钥，`/rewind` 也不会把它恢复回去：文件保持原样，
命令会告诉你是哪一个。

## 权限

- **五种模式**——`default`、`acceptEdits`、`plan`、`readonly`、`bypass`。
- **模型会知道**——`plan` 和 `readonly` 下 agent 知道自己改不了东西，
  于是把看到的说出来，而不是动手。
- **规则**——`~/.coderagent/rules.yaml` 和 `.coderagent/rules.yaml` 按工具
  和模式决定放不放行。**用户级那份赢**。
- **`Always allow`**——审批卡片上的这个按钮会写一条规则，以后**同一个调用**
  （同一个文件、同一条命令）直接放行。
- **禁止的路径**——`permissions.deny_paths`，agent 不许碰的路径。
- **额外的目录**——`permissions.include_dirs`，工作目录以外、agent 仍然
  可以碰的目录。
- **三个答案**——允许、拒绝、永久允许。没人回答就是拒绝：浏览器里等
  `ui.approval_timeout` 秒（默认五分钟），终端里一直等，因为那儿坐着人。
- **终端里用方向键选答案**，浏览器里点卡片上的按钮；没有终端时一律拒绝。
- **hook 跑在权限检查前面**——hook 可以改写这次调用或者拦下来，权限检查
  看到的是改写之后的那次。

### 用法例子

没有规则的时候，由模式决定：

| 模式 | `read`、`glob`、`grep`、`ls` | `write`、`edit`、`multi_edit` | `bash` | `todo_write`、`bash_output`、`bash_kill` |
|---|---|---|---|---|
| `default` | 允许 | 问 | 问¹ | 允许 |
| `acceptEdits` | 允许 | 允许 | 问¹ | 允许 |
| `plan` | 允许 | 拒绝 | 拒绝 | 允许 |
| `readonly` | 允许 | 拒绝 | 拒绝 | 允许 |
| `bypass` | 允许 | 允许 | 允许 | 允许 |

规则文件按工具和模式决定：

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

`pattern` 对路径类工具是 glob（`*` 在一段里，`**` 跨目录），对 `bash` 是
**正则**，别的工具就是工具名。对 `bash`，这个正则要对上命令**每一段的开头**：
`git push` 能对上 `git push origin main`，但对不上 `echo "git push"`。

¹ 只是看的命令——`ls`、`cat`、`grep`、`git status` 之类——直接放行，不问；
其余的问。详见下面的[命令行](#cli)。

```bash
coder -t "跑一下测试" --permission-mode acceptEdits
coder -t "这个要怎么修？" --permission-mode plan
```

`plan` 和 `readonly` 会往给模型看的消息里塞一段说明：

```xml
<permission_mode mode="plan">
You are in plan mode. You may only look around: `read`, `glob`, `grep` and `ls`
work, but every tool that changes something, `bash` included, is refused.
Investigate the task and answer with the plan you would follow. The user
decides whether it is executed.
</permission_mode>
```

审批上的 `Always allow` 会往 `~/.coderagent/rules.yaml` 写一条规则：

```yaml
rules:
  - tool: bash
    pattern: pytest
    decision: allow
    reason: always allowed by the user
```

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `Error: permission denied for 'write'. '{path}' is outside the working directory {cwd}` | agent 想碰工作目录以外的路径。 | 把那个目录加进 `permissions.include_dirs`，或者换工作目录。 |
| `Error: the user denied 'write'.` | 有人在审批那里拒了。 | 允许它，或者为它写条规则。 |
| `Error: 'write' needs approval but no approver is available. Run with --permission-mode bypass to allow it.` | 这次运行没有终端（脚本或者 CI），而工具要审批。 | `--permission-mode bypass`，或者一条 `decision: allow` 的规则。 |
| `{path}:{line}: invalid decision '{d}', expected one of allow, ask, deny` | 规则文件里的决定值不对。 | 用 `allow`、`ask` 或 `deny`。 |
| `{path}:{line}: unknown rule keys: {keys}` | 规则里有不存在的键。 | 键只有 `tool`、`pattern`、`decision`、`reason`。 |
| `{path}: invalid YAML: {error}` | 规则文件解析不了。 | 修 YAML，消息里带着行号。 |
| `{path}: \`rules\` must be a list` | `rules` 不是一个列表。 | 写成一个由映射组成的列表。 |
| `Error: permission denied for 'bash'. '{path}' is outside the working directory {cwd}` | 命令里点了工作目录以外的路径。 | 用工作目录里的路径，或者用 `permissions.include_dirs` 打开那个目录。 |

`decision: allow` 的规则**不会**把整块磁盘打开：工作目录以外的路径还是
碰不到，除非它在 `permissions.include_dirs` 里。用户级的规则也不能放宽这个
边界。

`permissions.deny_paths` 加的是一条「全部拒绝」的规则，它在规则文件之后
生效，所以同样路径上的 `allow` 打不过它。

### 命令行 {#cli}

`bash` 是唯一什么都能干的工具，所以它有三条边界。

**只是看的命令直接放行。** `ls`、`cat`、`head`、`tail`、`grep`、`diff`、`wc`、
`jq`，还有 `git` 里读东西的那些子命令（`status`、`diff`、`log`、`show`……）
是安全的：它们不改东西，也不联网，所以不问。

**会毁东西或者把东西送出去的命令要问。** `rm`、`mv`、`cp`、`chmod`、`curl`、
`wget`、`ssh`、`pip`、`npm`、`docker`、`git push` 这些。它们不是被拒绝——由
人来决定，审批上会写清楚这条命令干什么（「把数据送出这台机器」）。在
`bypass` 下它们照常放行，因为那儿没有人可问。

**工作目录以外的路径被拒绝。** `cat /etc/passwd`、`cat ../secret`、
`cat ~/.ssh/id_rsa`、`cd ..` 在任何模式下都被拒绝，和文件工具的路径一样。
系统的程序可以点名（`/bin/ls`），但数据不许离开工作目录。
`permissions.include_dirs` 可以打开工作目录以外的目录。

命令的每一段都单独判，取最严的那一段：放行了 `pytest` 也不代表跟着它的
`rm` 一起放行。

```bash
ls -la                       # 放行
git status                   # 放行
curl http://example.com      # 要问：把数据送出这台机器
pytest -q && rm -rf build    # 要问：rm 是危险的
cat /etc/passwd              # 拒绝
```

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

### 用法例子

```bash
coder -t "第一个任务"                     # 新会话
coder --list                              # 这个目录的会话
coder --resume 20261109-3f0a91 -t "接着说"  # 续上那个
coder --continue -t "接着说"                # 续上这个目录里最新的
coder --fork 20261109-3f0a91 -t "另一条路"  # 复制一份，原来那份不动
```

一个会话的文件都在 `~/.coderagent/` 里：

```
~/.coderagent/sessions/20261109-3f0a91.jsonl        # 事件日志
~/.coderagent/sessions/20261109-3f0a91.meta.json    # id、cwd、created_at、model_name
~/.coderagent/checkpoints/20261109-3f0a91.json       # 写文件前的快照
```

事件日志一行一个 JSON 对象，类型有 `user_message`、`assistant_message`、
`tool_call`、`tool_result`、`approval_request`、`approval_response`、
`state_change`、`compaction`、`reflection`、`verify`、`reverted_to`、`error`、
`turn_end`。

`/rewind` 只还原**文件**——命令对外部世界做过的事还是做过了——并把会话的
历史截断到快照那一刻。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `ValueError: no checkpoint '<id>' in this session` | `/rewind` 拿到的 id 不是这个会话的检查点。 | 不带 id 的 `/rewind` 会列出检查点。 |
| `/resume <不存在的 id>` 起了一个目录是 `.` 的会话 | 日志里没有这个 id 不会报错，它会造一个空会话。 | 用 `coder --list` 看看有哪些 id。 |
| 一轮以 `stop_reason: max_turns` 结束 | agent 用了 50 次模型调用还没完（`agent.max_turns`）。 | 调大 `agent.max_turns`，或者把任务拆小。 |
| 一轮以 `stop_reason: cost_exceeded` 结束 | 这一轮花的钱超过了 `agent.cost_limit`。`0` 是没有上限。 | 调大 `agent.cost_limit`。 |
| 一轮以 `stop_reason: token_limit` 结束 | 这一轮用的 token 超过了 `agent.token_limit`。`0` 是没有上限。模型没有价格时钱不动，token 就是预算。 | 调大 `agent.token_limit`。 |
| 一轮以 `stop_reason: error` 结束 | 模型调用重试完了还是失败。错误文本在 `error` 里。 | 看 `error`，那是厂商的消息。 |
| 一轮以 `stop_reason: interrupted` 结束 | 有人按了 `ctrl+c`。 | 会话已经存下来了，用 `--resume` 接着来。 |

以 `cost_exceeded` 或 `error` 结束的一轮**不会**被沉淀成记忆：记忆里只留
失败之前学到的东西。

## 上下文

- **token 是数出来的**——装了 tiktoken 就精确数，没装就估。
- **窗口跟着模型走**——DeepSeek 64k、Claude 200k、GPT 128k 这样。配置文件
  里写了 `context_window` 就以它为准。
- **自动压缩**——对话到窗口的 80 % 就做摘要、把历史缩短。摘要是结构化的：
  目标、发现、决定、动过的文件、没解决的问题、下一步、见过的错。
- **留什么**——最近几轮，或者最近 40 % 的 token，哪个多留哪个。
- **`/compact`**——随时手动压缩。
- **消息的顺序**——系统提示词、指令文件、todo、会话摘要，然后是历史。

### 用法例子

```yaml
context:
  context_window: 64000
  compact_threshold: 0.8
  keep_recent_turns: 20
  keep_recent_token_ratio: 0.4
  compact_every_turns: 40
  summarize_model: deepseek/deepseek-flash
```

配置里没有 `context_window` 时，窗口跟着模型名字走：`gpt-` 128k、`claude`
200k、`deepseek` 64k、`qwen` 32k、`llama` 8k、`gemini` 1M、`mistral` 32k、
`kimi` 256k、`minimax` 200k，别的都是 200k。

摘要是一个 JSON 对象，键是这些：

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

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `... (nothing left to compact)` | 这一轮因为上下文太大而失败，而且已经没什么可缩的了。 | 调大 `context.context_window`，调小 `context.reserved_output`，或者 `/clear` 重来。 |
| 摘要是个兜底版本，不是真的摘要 | 模型没按摘要的 JSON 回答。试两次之后就用保守摘要：最后五条消息，`next_steps` 是 `["re-read the files that were mentioned to recover the details"]`。 | 不用管，会话继续走。再问模型一次那些细节。 |
| `recent_errors` 是空的，但会话里明明有错 | 只有以 `Error:` 开头的工具消息会被收集，而且只留最后三条。 | 不用管。 |

token 的计数：装了 tiktoken 是精确的，没装是估的
`int(chars / 3.6) + 4 * len(messages)`。估小了会让压缩来晚一点，所以长会话
值得装 tiktoken。

## 记忆

- **项目记忆**——`.coderagent/memory`，一轮结束时把关于项目的东西写下来。
- **用户记忆**——`~/.coderagent/CLAUDE.md`，记用户的偏好。
- **偏好要等人确认**——先落在 `pending-memory.md`，`/memory confirm` 才写
  进去。
- **指令文件**——项目的 `AGENTS.md` 和 `CLAUDE.md`、用户的 `CLAUDE.md`，
  agent 都读。
- **可以关掉**——`memory.enabled`。

### 用法例子

三个文件：

```
.coderagent/memory/projects.md        # agent 学到的关于项目的东西
.coderagent/pending-memory.md         # 等着被确认的偏好
~/.coderagent/CLAUDE.md                # 已经确认过的偏好
```

一轮结束时，agent 看最后 40 条消息，把学到的写下来：

```markdown
# Project memory

- the tests of the API are run with `pytest tests/`, they need a postgres on localhost
- the release is made with `bump2version`, not with a manual edit of setup.py
```

用户的偏好先进 `pending-memory.md`：

```markdown
# Preferences waiting for a confirmation

- always answer in Chinese
```

`/memory confirm` 之后才进 `~/.coderagent/CLAUDE.md`：

```markdown
## Preferences

- always answer in Chinese
```

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `The memory was not written: {path} would grow past 200 lines; tidy it up first.` | 那个文件会超过 200 行。 | 把文件写短一点，或者拆开。 |
| 日志里的警告 `The reflection of the session failed` | 模型没有按预期的 JSON 回答，所以什么都没写。会话本身没事。 | 不用管，下一轮会再试。 |
| `Wrote 2 preference(s) to /Users/you/.coderagent/CLAUDE.md.` | 确认成功了。 | — |
| `Nothing like that in the memory.` | `/memory forget` 没找到那段文字。 | 用 `/memory` 看看现在有什么。 |
| `Removed.` | `/memory forget` 把那段文字删了。 | — |

记忆可以整个关掉：

```yaml
memory:
  enabled: false
```

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
- **MCP 服务器**——stdio。它们的工具和别的工具一样，工具名是
  `mcp__<服务器>__<工具>`，一样要审批，断了会自己重连。

### 用法例子

一个子 agent，`.coderagent/agents/scout.md`：

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

模型把它当工具调：

```json
{"tool": "task", "params": {"subagent_type": "scout", "description": "where is the auth?", "prompt": "find the auth code"}}
```

回答是一个 JSON 对象：

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

一个技能，`.coderagent/skills/release/SKILL.md`：

```markdown
---
name: release
description: How to make a release of this project
---

1. Run the test suite.
2. Run `bump2version patch`.
3. Push the tag.
```

一个 hook，写在配置里：

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

hook 从 stdin 读 JSON，往 stdout 写 JSON：

```json
{"decision": "block", "reason": "the command writes a secret"}
```

`decision` 是 `allow`、`deny` 或 `block`；hook 还可以带 `additionalContext`，
或者用 `updatedInput` 改写这次调用。工具的 `updatedInput` 是一份参数映射；
`UserPromptSubmit` 的 `updatedInput` 是一个字符串，用来改写用户的提问。

一个自己的命令，`.coderagent/commands/commit.md`：

```markdown
---
description: Make a commit of the changes
argument-hint: [message]
allowed-tools: bash, read
model: cheap
---

Commit everything with the message: $ARGUMENTS
```

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `Error: unknown sub agent 'scout'. Available sub agents: code-explorer, refactorer, verifier.` | 索引里没有这个子 agent。 | 用列出来的名字；自己写的那些在系统提示词的索引里。 |
| `Error: the sub agents are not available in this session.` | `task` 工具没注册——`tools.enabled` 被收窄了。 | 把 `task` 放回 `tools.enabled`。 |
| `Error: unknown skill 'release'. Available skills: {...}.` | 这个技能不存在。 | 技能是 `.coderagent/skills/<名字>/SKILL.md`。 |
| `Trusted 'x'. It is loaded the next time the agent starts.` | `/plugins trust x` 的回答。 | 下次起 agent 才会用上这个插件。 |
| `Error: the hook blocked 'bash'. the command writes a secret` | `PreToolUse` 的 hook 拒绝了这次调用。 | 改命令，或者改 hook。 |
| `Hook 'check_secrets.sh' timed out, ignoring it` | hook 跑得比它的超时久。调用放行。 | 调大 `timeout`，或者让 hook 快点。 |
| `Hook 'check_secrets.sh' failed with RuntimeError: ...` | hook 崩了。调用放行。 | 修 hook。加 `strict: true` 就会挡住调用。 |
| `Error: the MCP server 'echo' is not connected.` | 服务器没跑起来。 | 检查服务器的 `command`；`/mcp` 里会写 `not connected` 或者 `failed: <错误>`。 |
| `Error: the MCP tool 'echo' failed: RuntimeError: ...` | 服务器回的错。消息里的名字是服务器那边的名字。 | 服务器的消息就在答案里。 |

自己的命令只在 `<cwd>/.coderagent/commands/*.md` 里找——agent **不会**一层层
往上找。

## 沙箱

- **默认是本机**——命令就在工作目录里跑。
- **也可以是容器**——`docker`、`singularity`、`bubblewrap`、`contree`，
  还有 SWE-rex 的远程沙箱。和 mini-swe-agent 用的是同一批环境。
- **只有 `bash` 进沙箱**——文件工具还在工作目录里。
- **`/sandbox`**——告诉你命令在哪里跑。

### 用法例子

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
```

一共有七种：`local`、`docker`、`singularity`、`bubblewrap`、`contree`、
`swerex_docker`、`swerex_modal`。环境不认识的选项会被忽略，所以一个文件里
可以同时写好几种环境的设置。

`/sandbox` 回答类型、生效的选项和在用的环境：

```
type: local
environment: local
```

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `ValueError: Unknown environment type: nope (resolved to nope, available: {...})` | 类型不是那七种之一。 | 用上面列出的名字。 |
| `CalledProcessError: Command '[...]' returned non-zero exit status 1.` | 容器起不来，或者镜像拉不下来。 | 检查镜像名字，以及 docker 是不是在跑。 |
| `FileNotFoundError: [Errno 2] No such file or directory: 'singularity'` | 这个环境的二进制没装。 | 装上，或者换一个类型。 |
| 文件工具动到了宿主机的文件 | 只有 `bash` 进沙箱。 | 这是设计如此：`read`、`edit` 这些工具动的是会话的工作目录。 |

## 校验

- **默认不开**——不配 `verify.commands` 就什么都不查。
- **agent 必须把检查跑通**——模型想停下的时候命令会跑一遍；有一条没过，就把输出还给
  agent，让它接着改。
- **命令在会话的环境里跑**——有沙箱就在沙箱里，所以检查看到的世界和 agent 干活的
  世界是同一个。这些命令不ask要审批。
- **轮数有限**——`verify.max_rounds`（默认 3）。轮数用完，这一轮就以
  `stop_reason: verify_failed` 结束。
- **结果进事件日志**——一条 `verify` 事件记着命令和没过的那几条。

### 用法例子

```yaml
verify:
  commands:
    - python -m pytest -q
  max_rounds: 3
  timeout: 300
```

模型说做完了、而测试没过的时候，agent 会收到这样一段：

```
[verify] These commands did not pass. Fix the problem and try again.

$ python -m pytest -q
2 failed, 1 passed
[exit code 1]
```

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| 这一轮以 `stop_reason: verify_failed` 结束 | `verify.max_rounds` 轮用完了，命令还是没过。 | 在事件日志里看最后一轮的输出。 |
| 检查在沙箱里跑，但找不到文件 | 沙箱里没有会话的工作目录。 | 给环境配一个工作目录，或者用 `local`。 |
| 检查跑太久 | 命令超过 `verify.timeout` 秒被杀掉了。 | 调大 `verify.timeout`。 |
| agent 反复改同一处 | 检查要的东西 agent 做不到。 | 改检查，或者改任务。 |

## 终端界面

- **答案是流式出来的**——正文和思考过程都是。
- **状态栏**——模型、token、花费、目录、权限模式。
- **工具卡片**——这次调用、输出、以及这次改动的 diff。
- **审批**——`y`、`n`、`a`，或者方向键在带编号的列表上选。
- **长输出折起来**——有意思的那部分留在眼前。
- **todo 面板**——这一轮要做的事。

### 用法例子

状态栏长这样：

```
deepseek/deepseek-flash | 1.5k/64k | $0.0000 | ~/work/project | default
```

审批是一个带编号的列表，选中的那个有标记：

```
1 [*] y allow
2 [-] n deny
3 [-] a always allow
```

`←`/`→` 移动光标，`↑`/`↓` 也一样，数字键直接跳到那一行，空格切换多选，
`enter` 确认，`y`、`n`、`a` 直接回答。`ctrl+c` 打断这一轮，`ctrl+q` 收尾
会话并退出。

todo 面板用 `◉`（完成）、`◐`（进行中）、`○`（待办）标记任务状态。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| 工具要审批时界面没反应 | 没有终端——这次运行是无头的。 | 这次调用会被拒。用 `--permission-mode bypass` 或者写条规则。 |
| 工具输出下面有 `▸ 42 more lines` | 输出比卡片长。 | 有意思的部分还在眼前；要全文就打开文件，或者把命令的输出调少再跑一次。 |
| 界面起不来 | 终端里不给任务的 `coder` 会起界面；没有终端就打印 `no task given`。 | 用 `coder --tui` 强制起。 |

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

### 用法例子

```bash
coder web --cwd . --port 8765
```

```
coder web: http://127.0.0.1:8765
```

接口就是普通 HTTP。给会话发一条消息：

```bash
curl -X POST http://127.0.0.1:8765/api/sessions/20261109-3f0a91/messages \
  -H 'X-Coder-Client: 1' -H 'Content-Type: application/json' \
  -d '{"text": "run the tests"}'
```

订阅会话的事件流：

```bash
curl -N http://127.0.0.1:8765/api/sessions/20261109-3f0a91/stream
```

接口一览：

| 接口 | 干什么 |
|---|---|
| `GET /api/sessions` | 工作目录里的会话 |
| `POST /api/sessions` | 新建会话 |
| `GET /api/sessions/{id}` | 一个会话 |
| `GET /api/sessions/{id}/events` | 会话的事件 |
| `GET /api/sessions/{id}/items` | 某个序号之后的条目 |
| `GET /api/sessions/{id}/stream` | 事件流（SSE） |
| `GET /api/sessions/{id}/status` | 状态、模型、token、花费 |
| `GET /api/sessions/{id}/metrics` | 会话的指标 |
| `GET /api/sessions/{id}/changes` | 改动过的文件 |
| `POST /api/sessions/{id}/resume` | 续接会话 |
| `POST /api/sessions/{id}/fork` | 复制会话 |
| `POST /api/sessions/{id}/messages` | 发消息 |
| `POST /api/sessions/{id}/interrupt` | 打断这一轮 |
| `POST /api/sessions/{id}/mode` | 改这个会话的权限模式 |
| `POST /api/approvals/{id}` | 回答审批 |
| `GET /api/commands` | slash 命令 |
| `GET /api/config` | 配置和它的层 |
| `PUT /api/config/model` | 把模型写进用户级文件 |
| `GET /api/config/model/key` | 端点的 key |
| `PUT /api/config/permissions` | 把权限写进用户级文件 |
| `POST /api/config/model/test` | 一次最便宜的调用，测模型 |
| `GET /api/files` | 工作目录里的文件 |
| `GET /api/file` | 一个文件 |
| `GET /api/diff` | 一个文件的 diff |
| `GET /api/i18n/{language}` | 一种语言的文案 |

### 出错时怎么办

| 状态码 | 消息 | 什么意思 | 怎么办 |
|---|---|---|---|
| 403 | `the X-Coder-Client header is missing` | 写操作没带那个头。别的站点的浏览器发不出这个头。 | 加上 `-H 'X-Coder-Client: 1'`。 |
| 404 | `there is no session with the id {id}` | id 不存在。 | `GET /api/sessions` 看列表。 |
| 404 | `no approval is waiting for the id {id}` | 这个审批已经答过了，或者它超时了。 | 不用管。 |
| 404 | `unknown language` | `/api/i18n/{language}` 的语言没上线。 | 用 `en` 或 `zh`。 |
| 400 | `the message is empty` | 消息没有内容。 | 给点文字。 |
| 400 | `unknown permission mode '{value}'` | 模式不是那五个之一。 | 用 `default`、`acceptEdits`、`plan`、`readonly` 或 `bypass`。 |
| 400 | `the decision must be allow, deny or always` | 审批的回答不对。 | 用 `allow`、`deny` 或 `always`。 |
| 400 | `'{path}' is not a directory` | 文件接口的路径是个文件。 | 换成目录。 |
| 403 | `'{path}' is outside the working directory {cwd}` | 路径走出了工作目录。 | 没有办法——这就是边界。 |
| 409 | `the session {id} is running` | 会话正忙着，不能复制或续接。 | 等这一轮结束，或者打断它。 |

没人回答的审批在 `ui.approval_timeout` 秒之后被拒，浏览器会收到
`timed_out: true`。

批准一个会改文件的工具，会往 `~/.coderagent/rules.yaml` 写一条规则——和
终端用的是同一个文件。

服务起来时会把地址打出来。用 `--host 0.0.0.0` 时它会警告：

```
The web interface listens on 0.0.0.0: everybody who can reach that address can drive the agent.
```

## 配置

- **四层**——包里的默认值、项目文件 `.coderagent/config.yaml`、用户文件
  `~/.coderagent/config.yaml`、命令行的覆盖（`-c key=value`）。后面的赢。
- **有哪些段**——`model`、`agent`、`tools`、`permissions`、`context`、
  `memory`、`checkpoint`、`mcp`、`hooks`、`ui`、`sandbox`、`verify`。
- **路径**——`MSWEA_CODER_HOME` 可以把用户级文件挪到别处。
- **设置页只写用户级文件**——项目级那份在仓库里，永远不写。

### 用法例子

```bash
# 一个文件。
coder -t "..." -c myconf.yaml
# 覆盖，可以给多次。
coder -t "..." -c model.model_name=deepseek/deepseek-chat -c agent.max_turns=20
```

四层，从低到高：

1. 包里的默认值（`src/coderagent/config/defaults.yaml`），
2. 项目的 `.coderagent/config.yaml`，
3. 用户的 `~/.coderagent/config.yaml`，
4. 命令行的 `-c`。

模型名按这个顺序找：命令行的 `-c`、项目文件、用户文件、
`$MSWEA_MODEL_NAME`，最后是 `anthropic/claude-sonnet-4-5`。

各段和它们的键：

| 段 | 键 |
|---|---|
| `model` | `model_name`、`model_kwargs`、`max_retries`、`litellm_config`、`routing`、`routing_rules`、`set_cache_control` |
| `agent` | `system_prompt`、`max_turns`、`cost_limit`、`token_limit` |
| `tools` | `enabled`、`disabled`、`bash_timeout`、`max_output_tokens`、`schema_budget_tokens` |
| `permissions` | `mode`、`rules`、`deny_paths`、`include_dirs` |
| `context` | `context_window`、`reserved_output`、`compact_threshold`、`keep_recent_turns`、`keep_recent_token_ratio`、`compact_every_turns`、`auto_compact`、`summarize_model`、`summary_chunk_tokens` |
| `memory` | `project_path`、`user_path`、`enabled` |
| `checkpoint` | `enabled`、`keep` |
| `mcp` | `servers`、`timeout` |
| `hooks` | `events` |
| `ui` | `theme`、`show_reasoning`、`approval_timeout` |
| `sandbox` | `type` 和环境的那些选项 |

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| 什么都没发生，设置被忽略了 | 不存在的键会被静默忽略。 | 按上面的表核对拼写。 |
| `yaml.scanner.ScannerError` | 某一层的 YAML 解析不了。 | 修 YAML，消息里带着行号。 |
| `pydantic_core.ValidationError` | 值的类型不对——该是数字的地方写了字符串。 | 消息里说了是哪个字段。 |
| `FileNotFoundError: Could not find config file for ... (tried: [...])` | 给了 `-c myconf.yml`，但找的是 `myconf.yaml`。 | 用带 `.yaml` 的名字，或者给全路径。 |
| 模型不是文件里写的那一个 | 上面的一层赢了。 | 记住顺序；设置页上有各层的列表。 |
| `ui.show_reasoning` 没有效果 | 这个键存在，但还没有人读它。 | 终端里模型的思考过程一直都是显示的。 |

## 命令

二十五个内置命令：`/help`、`/model`、`/mode`、`/plan`、`/compact`、
`/clear`、`/resume`、`/fork`、`/rewind`、`/diff`、`/init`、`/cost`、
`/todos`、`/mcp`、`/permissions`、`/hooks`、`/agents`、`/skills`、
`/plugins`、`/memory`、`/status`、`/sandbox`、`/export`、`/context`、
`/exit`（别名 `/quit`）。

自己的命令放在 `.coderagent/commands/*.md`，和它们一起用。

### 用法例子

```bash
coder -t "/cost"          # 终端里跑一个命令
coder -t "/model deepseek/deepseek-chat"
coder -t "/mode plan"
```

带参数的命令，参数是这一行的剩下的部分：

```
/model deepseek/deepseek-chat
/rewind 20261109-3f0a91
```

浏览器里，命令在聊天页的命令面板里，列表来自 `GET /api/commands`。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| `Unknown command '/foo'. Try /help.` | 没有这个命令。 | `/help` 看列表，`/help <名字>` 看某一个。 |
| `Unknown mode 'bogus'. Use one of: default, acceptEdits, plan, bypass, readonly.` | `/mode` 给了一个不存在的模式。会话的模式没变。 | 用那五个之一。 |
| `/rewind` 拿到的 id 不是检查点 | `ValueError: no checkpoint '<id>' in this session` | 不带 id 的 `/rewind` 会列出检查点。 |
| `Not a git repository: {cwd}` | `/diff` 跑的是 `git diff`，而这个目录不是仓库。 | 在仓库里跑，或者看网页版的改动。 |
| `{path} already exists.` | `/init` 不会覆盖已有的 `AGENTS.md`。 | 自己改那个文件。 |
| `No sessions yet.` | `/resume` 不带 id 时，这个目录里什么都没有。 | 先跑一轮。 |

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

### 用法例子

```bash
mini --model litellm/deepseek/deepseek-flash --environment-class docker \
  --task "the failing test is in test_api.py"

mini-extra swebench --model litellm/deepseek/deepseek-flash --workers 8 \
  --slice 0:100
```

一次运行的轨迹是一个 JSON 文件，里面有每一步的消息、工具调用和花费；
`inspector` 读它。

### 出错时怎么办

| 你看到的 | 什么意思 | 怎么办 |
|---|---|---|
| 环境建不起来 | 镜像没有，或者这个环境的二进制没装。 | 和 coding agent 的沙箱那些错误一样。 |
| 模型回答里没有工具调用 | benchmark 用的模型是基于文本的，或者回答的格式不对。 | 换一个会说工具协议的模型，或者用 benchmark 里有包装的那个模型类。 |

## 细节在哪

| 文档 | 里面有什么 |
|---|---|
| [coding agent 概览](coderagent.md) | 从第一次会话到所有文件，全套 |
| [命令](coderagent_commands_zh.md) | 每个命令，以及自己的命令 |
| [网页版](coderagent_web_zh.md) | 聊天页、设置页、API |
| [子 agent](coderagent_subagents_zh.md) | 怎么写一个子 agent |
| [技能](coderagent_skills.md) | 怎么写一个技能 |
| [hook](coderagent_hooks_zh.md) | 六个时机和 hook 的回答 |
| [插件](coderagent_plugins.md) | 怎么写一个插件 |
| [MCP 服务器](coderagent_mcp.md) | 服务器怎么配 |
| [记忆](coderagent_memory.md) | 那些文件和确认 |
| [模型路由](coderagent_routing.md) | 用途和规则 |
| [沙箱](coderagent_sandbox.md) | 那些环境 |
| [追踪导出](coderagent_export.md) | 一个会话的追踪 |
| [快速开始](coderagent_quickstart.md) | 头十分钟 |
