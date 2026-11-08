# 快速开始

本页用最短的路径把 `coder`（本仓库里的交互式 coding agent）跑起来，并说明日常怎么用它。

- [安装](#install)
- [配置模型和 API key](#model)
- [第一次会话](#first-session)
- [也可以在浏览器里跑](#web)
- [不用终端的用法](#headless)
- [权限：agent 改文件前要问你](#permissions)
- [常用命令](#commands)
- [给项目写一份配置](#config)
- [扩展：子 agent、skills、命令](#extensions)
- [会话与花费](#sessions)
- [常见问题](#faq)

## 安装 {#install}

从源码装（要改代码就用这个）：

```bash
git clone https://github.com/SWE-agent/mini-swe-agent.git
cd mini-swe-agent
pip install -e .
```

装完有两个命令：

| 命令 | 是什么 |
|---|---|
| `coder` | 交互式 coding agent，本页的主角 |
| `mini` | mini-swe-agent 本体，跑 SWE-bench 之类的任务 |

可选依赖：

```bash
pip install -e ".[mcp]"    # MCP 服务器
pip install -e ".[full]"   # 沙箱（swerex / modal / contree）等一切
```

## 配置模型和 API key {#model}

模型走 [litellm](https://github.com/BerriAI/litellm)，所以任何 litellm 支持的模型都能用，只要带上厂商前缀（`anthropic/…`、`deepseek/…`）。

API key 从环境变量读，名字就是厂商的名字：`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`OPENROUTER_API_KEY`……完整列表见[模型配置](../models/quickstart.md)。

有三种写法，任选一种：

```bash
# 1. 写进全局 .env（推荐，一次搞定，所有会话都能用）
mini-extra config set ANTHROPIC_API_KEY sk-...
mini-extra config set MSWEA_MODEL_NAME anthropic/claude-sonnet-4-5

# 2. 当前 shell 的环境变量（重启 shell 就没了）
export ANTHROPIC_API_KEY=sk-...
export MSWEA_MODEL_NAME=anthropic/claude-sonnet-4-5

# 3. 命令行直接指定
coder -m deepseek/deepseek-flash --task "..."
```

全局 `.env` 在 `mini-extra config edit` 打印的那个路径（macOS 上是
`~/Library/Application Support/mini-swe-agent/.env`）。

模型的优先级是：**配置文件里的 `model.model_name` > 环境变量 `MSWEA_MODEL_NAME` > 内置默认值**。
没配置时默认用 `anthropic/claude-sonnet-4-5`。

### 换别的厂商 {#providers}

litellm 支持的模型都能用，模型名里带厂商前缀，key 从同名环境变量读：

| 模型名 | 厂商 | 环境变量 |
|---|---|---|
| `anthropic/claude-sonnet-4-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `openai/gpt-4o` | OpenAI | `OPENAI_API_KEY` |
| `deepseek/deepseek-flash` | DeepSeek | `DEEPSEEK_API_KEY` |
| `dashscope/qwen3-coder-plus` | 阿里（DashScope） | `DASHSCOPE_API_KEY` |
| `moonshot/kimi-k2.5` | 月之暗面 | `MOONSHOT_API_KEY` |
| `minimax/minimax-m2` | MiniMax | `MINIMAX_API_KEY`（外加 `MINIMAX_API_BASE`） |
| `openrouter/qwen/qwen3-coder` | OpenRouter | `OPENROUTER_API_KEY` |

```bash
export DASHSCOPE_API_KEY=sk-...
coder -m dashscope/qwen3-coder-plus --task "..."

export MOONSHOT_API_KEY=sk-...
coder -m moonshot/kimi-k2.5 --task "..."

export MINIMAX_API_KEY=...
export MINIMAX_API_BASE=https://api.minimax.io/v1
coder -m minimax/minimax-m2 --task "..."
```

三个坑：

- **`qwen/` 不是厂商。** 千问在 `dashscope/` 下（`qwen_ai_platform/` 是它的旧名）。`qwen/` 是模型系列的名字，不是路由。
- **上下文窗口按模型名查表**：`qwen` 32k、`deepseek` 64k、`kimi` 256k、`minimax` 200k、`claude` 200k、`gpt-` 128k、`gemini` 1M。遇到新模型或表里没有的系列，自己写：`context.context_window: 262144`。
- **模型必须支持工具调用（tool calling）**，否则用不了。系列里的小模型常常不支持，只在 `model.routing.cheap` 里用它们。

混用厂商时用路由分层：主力模型干活，便宜模型做杂活。

```yaml
model:
  model_name: dashscope/qwen3-coder-plus
  routing:
    cheap: moonshot/kimi-k2.5
    summarize: moonshot/kimi-k2.5
```

## 第一次会话 {#first-session}

```bash
cd my-project
coder
```

界面顶部是状态栏：模型、上下文用量、本次会话花了多少钱、当前目录、沙箱、权限模式。

直接说人话就行：

```
fix the failing test in tests/test_parser.py
```

agent 会自己读代码、改文件、跑测试。写入文件前它会先存一个 checkpoint，可以用 `/rewind` 退回去。

## 也可以在浏览器里跑 {#web}

```bash
pip install -e ".[web]"
coder web
```

同一个 agent，在浏览器里跑：聊天页是终端界面的窗口版，设置页可以把模型和 API key 配好（API key 只写进用户级的 `~/.coderagent/config.yaml`，永远不明文回浏览器）。

注意**没有认证**：能访问端口的人就能驱动 agent 在当前目录里跑命令，所以默认只听 `127.0.0.1`。详见[网页版](coderagent_web_zh.md)（[English](coderagent_web.md)）。

## 不用终端的用法 {#headless}

CI、脚本、或者只有一条消息要问的时候：

```bash
coder --task "fix the failing test in tests/test_parser.py"
```

输出是对话加一行本轮的账：

```
[stop_reason=end_turn cost=0.0016 session_cost=0.0019 session=20261106-a1b2c3]
```

`cost` 是这一轮，`session_cost` 是整个会话。要机器读就加 `--output-format json`：

```json
{
  "session_id": "20261106-a1b2c3",
  "messages": [{"role": "assistant", "content": "The test needed a fixture."}],
  "cost": 0.0016,
  "session_cost": 0.0019,
  "stop_reason": "end_turn",
  "error": ""
}
```

`stop_reason` 有五种：`end_turn`、`max_turns`、`cost_exceeded`、`interrupted`、`error`。

**没有终端就没人能批准操作**，所以默认模式下需要批准的调用一律被拒（拒绝的原因会告诉模型，模型会换个做法）。
脚本里如果确实需要它动手，加 `--permission-mode bypass`：

```bash
coder --task "..." --permission-mode bypass
```

## 权限：agent 改文件前要问你 {#permissions}

五种模式，`--permission-mode` 或者会话里 `/mode` 切换：

| 模式 | 行为 |
|---|---|
| `default` | 读随便读，写文件和跑命令要问你 |
| `acceptEdits` | 写文件不问，跑命令要问你 |
| `plan` | 只读不改，agent 只看不碰 |
| `readonly` | 同 plan，但 agent 知道自己不能写 |
| `bypass` | 全放行。只在容器或一次性 checkout 里用 |

界面里被问到的时候：`y` 允许这一次，`n` 拒绝，`a` 本次会话都允许。
选项是一行一个、带编号的方框，选中的那个是红星 `[*]`，没选的是灰杠 `[-]`：

```
1 [*] y allow
2 [-] n deny
3 [-] a always allow
```

方向键（`←`/`→` 或 `↑`/`↓`）移动选中项，数字键直接跳到那一项，回车确认。
拒绝的理由会回到模型，模型会改主意而不是硬来。

想固定某些规则，写在 `.coderagent/rules.yaml`（项目）和 `~/.coderagent/rules.yaml`（用户）：

```yaml
rules:
  - tool: bash
    pattern: "pytest"
    decision: allow
  - tool: edit
    pattern: "tests/**"
    decision: allow
```

`decision` 是 `allow` / `ask` / `deny`，最后一条匹配上的规则赢。

## 常用命令 {#commands}

会话里以 `/` 开头的是命令，其余都是给 agent 的话。常用的几个：

| 命令 | 作用 |
|---|---|
| `/help` | 所有命令的列表 |
| `/plan` | 切成只读模式，先让它给出方案 |
| `/mode` | 看/切权限模式 |
| `/cost` | 这次会话花了多少钱，花在哪 |
| `/diff` | 看工作区的改动 |
| `/init` | 给项目生成一份 `AGENTS.md` |
| `/todos` | agent 的任务清单 |
| `/clear` | 开一个新会话（账从 0 开始） |
| `/rewind` | 看 checkpoint，指定 id 就退回去 |
| `/status` | 会话的状态 |
| `/context` | 上下文用了多少 |

完整列表在 [`/help` 的输出](coderagent_commands.md)里。

## 给项目写一份配置 {#config}

在项目根目录放 `.coderagent/config.yaml`，四层配置里它排第二（后面还有用户级的 `~/.coderagent/config.yaml` 和命令行的 `-c key=value`，越靠后越优先）：

```yaml
model:
  model_name: deepseek/deepseek-flash
  routing:
    cheap: deepseek/deepseek-flash
    summarize: deepseek/deepseek-flash

agent:
  max_turns: 50
  cost_limit: 5.0

tools:
  enabled: [read, write, edit, glob, grep, ls, bash, todo_write]
  bash_timeout: 120

permissions:
  mode: default
  deny_paths: ["*.env", "secrets/**"]

context:
  context_window: 64000
  compact_threshold: 0.8

memory:
  enabled: true

sandbox:
  type: local
```

每个键的完整说明在[配置总览](coderagent.md#the-configuration)。

!!! warning "`tools.enabled` 是白名单，会**替换**默认列表"
    默认的工具是 `read, write, edit, multi_edit, glob, grep, ls, bash, bash_output, bash_kill, todo_write, task, skill`。
    你一旦写了 `tools.enabled`，没列进去的工具就没了——上面的例子会去掉 `multi_edit`、`task`（子 agent）和 `skill`。
    想减工具用 `tools.disabled`，它只拿走你点名的那些。

命令行临时改一个键：

```bash
coder -c model.model_name=deepseek/deepseek-flash -c permissions.mode=plan
```

## 扩展：子 agent、skills、命令 {#extensions}

三样东西都在项目的 `.coderagent/` 下：

```
.coderagent/
├── config.yaml       # 配置
├── rules.yaml        # 权限规则
├── agents/*.md       # 子 agent：独立上下文干一件活
├── skills/*/SKILL.md # skill：带脚本和资源的可复用能力包
├── commands/*.md     # 自定义命令
└── memory/           # agent 记住的项目事实
```

**子 agent** 适合「全仓找某个符号」这种会把主上下文撑爆的活：

```markdown
---
name: doc-writer
description: 给一个模块写文档。
tools: [read, grep, glob]
model_purpose: cheap
max_turns: 15
---
你是模块文档专家，先读代码再写文档。
```

**自定义命令**是给用户用的 `/name`：

```markdown
---
description: 生成提交信息
argument-hint: [file]
---
描述 $1 的改动。
```

细节见[子 agent](coderagent_subagents.md)、[skills](coderagent_skills.md)、[命令](coderagent_commands.md)。

## 会话与花费 {#sessions}

每个会话是一份只追加的事件日志，**它是唯一的事实来源**，存在 `~/.coderagent/sessions/`。

```bash
coder --list              # 这个目录的会话
coder --resume <id>       # 接着聊
coder --fork <id>         # 复制一份再接着聊
coder export --session <id> --format json --out trace.json
coder export --session <id> --format otel --out trace.otlp
```

账是**每个会话自己的**：`/clear` 之后的新会话从 0 开始，不会背着上一段会话的账。`cost_limit` 也是每个会话的预算。

`/cost`、`/status` 和 `coder export` 报的是同一个数字。

## 常见问题 {#faq}

**「找不到 API key」**
key 必须在环境变量里，或者在 `mini-extra config edit` 打印的那个 `.env` 里。
`coder` 启动时会静默地读这个 `.env`，读不到就报认证错误。
查一下当前进程里到底有没有：

```bash
python -c "import coderagent.ui.cli, os; print(os.getenv('ANTHROPIC_API_KEY'))"
```

**「改了文件但我没同意」**
默认模式下写文件要批准，界面里按 `y` 允许这一次、`a` 本次会话都允许。或者用 `/mode acceptEdits`。脚本里用 `--permission-mode bypass`。

**「agent 一直问我要批准」**
在 `.coderagent/rules.yaml` 里放一条规则，把这个工具定成 `allow`。

**「上下文满了 / 越聊越慢」**
上下文到窗口的 `compact_threshold`（默认 0.8）就会自动压缩，把老的部分换成摘要。也可以随时 `/compact`。用 `/context` 看用量。

**「上一轮改的东西怎么找回来」**
`/rewind` 看 checkpoint，带 id 就把文件和对话一起退回去。默认保留最近 50 个（`checkpoint.keep`）。

**「想换个模型」**
会话里 `/model <名字>`，或者 `coder -m <名字>`。也可以在配置里写 `model.routing`，让压缩、总结、子 agent 各自用便宜的模型。

**「agent 好像忘了项目的事」**
会话结束时它会把值得记的事实写进 `.coderagent/memory/projects.md`。用 `/memory` 看。也可以直接写 `AGENTS.md` 或 `CLAUDE.md`，agent 开工前会读。

**「怎么知道它干了什么、花了多少钱」**
`coder export --session <id> --format json --out trace.json` 导出完整轨迹和指标；`/cost` 看实时账。
