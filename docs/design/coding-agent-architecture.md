# Coding Agent 架构设计（基于 mini-SWE-agent）

> 目标：在 mini-SWE-agent 的极简哲学之上，构建一个对标 Codex CLI / Claude Code 的交互式 coding agent。
> 技术栈：Python 3.10+ / litellm / pydantic / typer / jinja2，代码位于 `src/coderagent/`。

---

## 1. 定位与差异

mini-SWE-agent 是**基准测试用的极简单轮 agent**：一个 bash 工具、线性历史、跑完即弃。
我们要做的 coding agent 是**日常开发工具**：多轮会话、结构化工具、权限与沙箱、上下文治理、扩展生态。

因此不能直接改造 mini 的主循环（它的线性历史假设是硬约束），而应**复用其下半部分，重写其上半部分**：

| 复用（不改） | 重写（新增） |
|---|---|
| `Model` / `Environment` / `Agent` Protocol 风格 | 多轮会话循环（Session/Run 分离） |
| `litellm` 模型封装、缓存控制、成本核算 | 工具系统（结构化 tool calling + 权限策略） |
| YAML 配置体系 `get_config_from_spec` | 上下文引擎（compaction / 分层记忆） |
| `LocalEnvironment` 的 `subprocess.run` 沙箱原语 | 会话持久化与恢复（resume / fork / checkpoint） |
| `minisweagent.exceptions` 的异常分层 | MCP / Hooks / Skills / Subagent 扩展层 |

---

## 2. 能力差距分析

### 2.1 mini-SWE-agent 现状

```
bash 工具（唯一）  →  线性 messages 列表  →  单步/单会话  →  无权限模型  →  无上下文治理
```

### 2.2 目标能力矩阵

| 能力 | Codex CLI | Claude Code | mini-swe-agent | 本项目目标 |
|---|---|---|---|---|
| 结构化工具（read/write/edit/glob/grep） | ✅ | ✅ | ❌ 仅 bash | ✅ L2 工具系统 |
| 工具并行调用 | ✅ | ✅ | ❌ 串行 | ✅ 批量调度 |
| 沙箱 + 网络策略 | ✅ seatbelt/landlock | ✅ | ⚠️ 仅容器隔离 | ✅ 权限策略层 + 复用容器 |
| 审批模式 | ✅ 3 档 | ✅ 4 档 | ⚠️ human/confirm/yolo | ✅ 统一 PermissionMode |
| 会话恢复 / fork | ✅ rollout 文件 | ✅ | ❌ 只存档 | ✅ SessionStore |
| 上下文压缩 | ✅ 自动 | ✅ 自动 + 手动 | ❌ | ✅ ContextEngine |
| 项目指令文件 | ✅ AGENTS.md | ✅ CLAUDE.md | ❌ | ✅ 多源指令加载 |
| MCP | ✅ | ✅ | ❌ | ✅ 扩展层 |
| 子 Agent 委派 | ⚠️ | ✅ Task | ❌ | ✅ 后置 |
| Hooks | ❌ | ✅ | ❌ | ✅ 后置 |
| 终端 diff 预览 | ✅ | ✅ | ❌ | ✅ L5 |
| 流式输出 | ✅ | ✅ | ❌ | ✅ L4 |
| 多模型路由 | ✅ | ✅ | ⚠️ 单模型 | ✅ L4 ModelRouter |
| 浏览器界面 | ❌ | ❌ | ❌ | ✅ M5 Web 版（FastAPI + SSE） |

---

## 3. 总体分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  L5  交互层  CLI(typer) / TUI(textual) / Web(FastAPI+SSE)   │
│      流式渲染 · diff 预览 · slash 命令 · 审批交互             │
├─────────────────────────────────────────────────────────────┤
│  L4  模型网关  ModelGateway                                │
│      多模型路由 · 流式 · 重试 · 成本核算 · prompt cache      │
├─────────────────────────────────────────────────────────────┤
│  L3  上下文引擎  ContextEngine                             │
│      历史管理 · 压缩(compaction) · 分层记忆 · 预算守卫       │
├─────────────────────────────────────────────────────────────┤
│  L2  工具层  ToolRegistry / ToolExecutor / PermissionPolicy │
│      read·write·edit·glob·grep·ls·bash·todo·web·task·mcp   │
├─────────────────────────────────────────────────────────────┤
│  L1  执行层  Environment（local / docker / bubblewrap / …）  │
│      命令执行 · 超时 · 进程组 · 输出截断                      │
├─────────────────────────────────────────────────────────────┤
│  L0  会话内核  Session / Run / EventBus / SessionStore      │
│      状态机 · 事件流 · 持久化 · 恢复 · 检查点                │
└─────────────────────────────────────────────────────────────┘
        ↕  横切：Config(多层 YAML+TOML) · Hooks · Telemetry
```

**数据流（一次 turn）**

```
User input
   │
   ▼
Session.append_user_msg ──► ContextEngine.build_messages()  ← 注入 CLAUDE.md/AGENTS.md
   │
   ▼
AgentLoop.step() ──► ModelGateway.query(stream=True)
   │                     │
   │                     ▼  assistant msg (含 tool_calls) + reasoning
   │                     │
   │                     ▼
   │              ToolExecutor.plan(actions)
   │                     │  ← PermissionPolicy.check() → 可能触发审批 → EventBus
   │                     ▼
   │              并行执行 → Environment.execute()
   │                     │
   │                     ▼
   │              ToolResult[] → ContextEngine.append_tool_results()
   │
   └──► 重复直到 stop_reason / 限额 / 用户中断
         │
         ▼
   SessionStore.persist()  →  .coderagent/sessions/<id>.jsonl
```

**三种前端，一套内核**：CLI（typer）、TUI（textual）、Web（FastAPI + SSE）跑的是同一套
loop / 工具 / 权限 / 事件日志；TUI 与 Web 都是 `EventBus` 的**订阅者**，不各自实现循环。
Web 版尤其如此——它把每个会话的 turn 放在自己的 worker 线程里跑，再把 `Event` 翻译成前端
条目推给浏览器，核心逻辑一行没改（详见 §4.6 的 Web 一节与
[M5-web-interface.md](milestones/M5-web-interface.md)）。

---

## 4. 模块设计

### 4.1 L0 会话内核

核心是把 mini 的 `DefaultAgent`（一次 `run()` 跑到底）拆成 **Session（持久状态）** 与 **Run（一次执行）**。

```python
# src/coderagent/core/session.py
class SessionState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    DONE = "done"
    ERROR = "error"


@dataclass
class Session:
    """一次用户可见的会话：可跨多次 run 恢复。"""
    id: str
    created_at: float
    updated_at: float
    cwd: Path
    state: SessionState = SessionState.IDLE
    model_name: str = ""
    permission_mode: str = "default"
    metadata: dict = field(default_factory=dict)


class SessionStore:
    """会话持久化。JSONL 追加写，天然支持流式落盘与崩溃恢复。"""
    def __init__(self, root: Path): ...
    def create(self, cwd: Path) -> Session: ...
    def load(self, session_id: str) -> Session: ...
    def append(self, session_id: str, event: dict) -> None: ...
    def list(self, cwd: Path | None = None) -> list[Session]: ...
```

**事件溯源**：所有状态变更都以 `event` 追加到 JSONL，重放即可恢复。
事件类型：`user_message` / `assistant_message` / `tool_call` / `tool_result` / `approval_request` / `approval_response` / `state_change` / `compaction` / `error`。

`EventBus` 用于解耦：L5 的 UI 订阅事件流渲染，L2 的工具执行发布事件，L4 的模型网关发布 token 流。

```python
class EventBus:
    def __init__(self): self._subs: dict[str, list[Callable]] = {}
    def subscribe(self, topic: str, cb: Callable) -> None: ...
    def publish(self, topic: str, payload: dict) -> None: ...
```

### 4.2 L1 执行层

直接复用 `minisweagent.environments`，但扩展 `Environment` 协议以支持**多命令并行**与**工作目录隔离**：

```python
# src/coderagent/core/environment.py
class CodingEnvironment(Protocol):
    def execute(self, action: dict, cwd: str = "") -> dict: ...
    def execute_batch(self, actions: list[dict], cwd: str = "") -> list[dict]:
        """并行执行多个独立命令（Claude Code 风格的多工具调用）。"""
    def snapshot(self) -> str:
        """返回环境指纹（镜像 ID / 容器 ID），用于 checkpoint。"""
    def restore(self, snapshot: str) -> None: ...
```

实现策略：
- **默认**：`minisweagent.environments.local.LocalEnvironment` + `docker.DockerEnvironment`（后者作为 `--sandbox docker`）。
- **checkpoint**：在 `LocalEnvironment` 上用 `git stash`/`git diff` 快照文件树；在 Docker 上用 `docker commit` 快照镜像。

### 4.3 L2 工具层（核心增量）

mini 只有 `bash`。我们要引入**结构化工具注册表**，但保留 bash 作为「逃生舱」——这是 Claude Code 的关键设计取舍：专用工具精确可靠，bash 兜底灵活。

```
coderagent/tools/
├── registry.py       # ToolRegistry：注册、schema 生成、名称解析
├── base.py           # Tool 抽象 + ToolResult
├── context.py        # ToolContext（cwd、session、bus、policy 的注入容器）
├── builtin/
│   ├── fs.py         # read, write, edit, multi_edit, notebook_edit
│   ├── search.py     # glob, grep, ls
│   ├── shell.py      # bash
│   ├── web.py        # web_fetch, web_search
│   ├── todo.py       # todo_write, update_plan
│   └── task.py       # task（子 Agent 委派，后置）
└── mcp.py            # MCP client → 动态注册为工具
```

#### 工具抽象

```python
# src/coderagent/tools/base.py
@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict          # JSON Schema

    def run(self, params: dict, ctx: ToolContext) -> ToolResult: ...


@dataclass
class ToolContext:
    cwd: Path
    session: Session
    bus: EventBus
    policy: PermissionPolicy
    config: dict
```

`ToolRegistry` 负责：
1. 聚合内置工具 + MCP 工具 → 生成 OpenAI/Anthropic 兼容的 `tools` 参数（沿用 `litellm`）。
2. 工具描述按上下文预算裁剪（token 预算不足时优先丢弃低频工具）。
3. 名称冲突处理（MCP 同名工具加 `server__` 前缀）。

#### 关键工具语义（对齐 Claude Code）

- **`edit`**：字符串精确匹配替换。**必须**要求 `old_string` 在文件中唯一，否则报错返回。这避免了 `sed` 式的模糊替换风险。
- **`read`**：支持 `offset`/`limit`，默认带行号（`cat -n` 风格），大文件自动截断并提示。
- **`grep`**：优先调用 `rg`，无 `rg` 时回退 `grep -r`。结果带文件路径+行号+内容，且限制默认命中数（避免刷屏）。
- **`glob`**：按 pattern 排序返回路径列表，超出上限截断。
- **`bash`**：默认 timeout 120s；`run_in_background=True` 时返回 task id，长命令不阻塞。
- **`todo_write` / `update_plan`**：显式任务清单，让模型显式规划（Claude Code 的 ToDo 工具）。
- **`web_fetch` / `web_search`**：带域名白名单。

#### 权限策略

```python
# src/coderagent/tools/permissions.py
class PermissionMode(str, Enum):
    DEFAULT = "default"        # 读自动，写与 bash 需审批
    ACCEPT_EDITS = "acceptEdits"  # 文件编辑自动通过，bash 需审批
    PLAN = "plan"              # 只读，禁止一切写操作
    BYPASS = "bypass"          # 全自动（等同 mini 的 yolo）
    READONLY = "readonly"      # 只读，且要求模型只描述改动而不动手


@dataclass
class Rule:
    tool: str                    # 工具名或 "*"
    pattern: str = "*"           # 对 path/command 的 glob/regex
    decision: str                # "allow" | "deny" | "ask"
    reason: str = ""


class PermissionPolicy:
    """规则求值顺序：deny > ask > allow > 默认策略。"""
    def __init__(self, mode: PermissionMode, rules: list[Rule]): ...
    def check(self, tool: str, params: dict) -> str:
        """返回 allow / ask / deny。"""
```

规则来源分层（后者覆盖前者）：
`内置默认规则` → `项目级 .coderagent/rules.yaml` → `用户级 ~/.coderagent/rules.yaml` → `会话内临时授权`（用户输入「总是允许」）。

「总是允许」需要持久化到用户级规则文件——这是 Claude Code 体验的关键。

### 4.4 L3 上下文引擎

这是 mini-SWE-agent 与 Codex/Claude Code 差距最大的一块。mini 假设线性历史永不长；coding agent 必须处理：

1. **上下文窗口溢出**
2. **历史污染**（早期探索的无关文件内容）
3. **长会话成本**

#### 上下文构成

```
┌─ system prompt（固定）──────────────┐
│  角色定义 · 工具规范 · 环境信息      │
├─ project instructions（可刷新）─────┤
│  CLAUDE.md / AGENTS.md / .coderagent/│
├─ todo / plan state（当前）──────────┤
├─ tool results（近期 N 轮，原样）────┤
├─ summary of older history（压缩产物）┤
└─────────────────────────────────────┘
```

#### 压缩策略（Compaction）

触发条件：估算 token 数 > 阈值（默认 0.8 × context_window）**或** 距上次压缩超过 N 轮。

压缩流程：
1. 选取「保留窗口」= 最近 K 轮完整消息（含其 tool results）。
2. 对更早的消息生成结构化摘要，而不是自由文本摘要：

```yaml
summary:
  goal: 用户当前要达成什么
  findings:                     # 已确认的事实
    - "入口在 src/api/handler.py:42"
  decisions:                    # 已做的技术决策及理由
    - "用 Redis 而非内存缓存，因为需要跨进程共享"
  files_touched:                # 已修改/新建的文件及其作用
    - path: src/cache.py
      change: 新增 Redis 缓存层
  open_questions:               # 未解决的问题
    - "缓存失效策略尚未确定"
  next_steps:                   # 明确的下一步
    - "实现 TTL 并补充单测"
```

3. 用摘要替换被压缩的历史，**保留结构化 `files_touched` 并注入后续 prompt**——这是 Claude Code 的关键技巧，让模型不丢失对已改文件的认知。

#### 分层记忆

| 层 | 生命周期 | 内容 | 存储 |
|---|---|---|---|
| 工作记忆 | 当前 run | 原始 messages | 内存 + JSONL |
| 会话记忆 | 一个 session | 压缩摘要、todo、文件改动清单 | SessionStore |
| 项目记忆 | 项目级 | 架构约定、常用命令、代码风格 | `AGENTS.md` / `.coderagent/memory/*.md` |
| 用户记忆 | 跨项目 | 个人偏好、常用别名 | `~/.coderagent/CLAUDE.md` |

项目/用户记忆由 agent 在会话结束时的「经验沉淀」步骤写入（需要模型调用，成本可控）。

#### 预算守卫

```python
# src/coderagent/core/budget.py
@dataclass
class BudgetGuard:
    context_window: int
    reserved_output: int = 4096
    reserve_ratio: float = 0.15

    def should_compact(self, estimated_tokens: int) -> bool: ...
    def trim_tool_result(self, result: ToolResult, max_tokens: int) -> ToolResult:
        """超长输出裁剪：保留头尾，中间标注省略行数。"""
```

工具输出裁剪沿用 mini 的 `observation_template` 思路（头尾各 5000 字符），但改为**按 token 预算**而非固定字符数。

### 4.5 L4 模型网关

mini 是「一个 Model 实例」。Coding agent 需要**网关**：

```python
# src/coderagent/core/model_gateway.py
class ModelGateway:
    """按用途路由到不同模型，统一流式、重试、成本统计。"""
    def __init__(self, config: dict, bus: EventBus): ...

    def query(self, messages: list[dict], *, purpose: str = "main",
              tools: list[dict] | None = None, stream: bool = True) -> AsyncIterator[ModelEvent]: ...

    def complete(self, messages: list[dict], *, purpose: str = "summarize") -> str:
        """非流式便捷方法，用于压缩/经验沉淀等后台调用。"""
```

**用途路由（purpose）**：

| purpose | 用途 | 默认模型档位 |
|---|---|---|
| `main` | 主循环推理 | 中/高档 |
| `cheap` | 文件标题推断、路径分类等琐碎判断 | 廉价档 |
| `summarize` | 上下文压缩 | 廉价档 |
| `reflect` | 经验沉淀、错误归因 | 中档 |

**流式处理**：litellm 的 `stream=True` 增量返回。需要处理：
- 增量 tool_call 的参数拼接（JSON 片段拼接后再解析）
- reasoning/thinking 块的增量（Anthropic）
- 中断（用户 Ctrl-C）时保留已生成的部分

```python
@dataclass
class ModelEvent:
    type: str          # "text" | "reasoning" | "tool_call_delta" | "tool_call_done" | "usage" | "error"
    content: str = ""
    tool_call: dict | None = None
    cost: float = 0.0
```

重试沿用 `minisweagent.models.utils.retry`，但需区分：
- 可重试：429/5xx/超时
- 不可重试：认证失败/上下文超限（→ 触发压缩后重试一次）

**上下文超限的特殊处理**：捕获 `ContextWindowExceededError` → 强制压缩 → 重发一次。这是真实使用中最高频的失败模式。

### 4.6 L5 交互层

#### CLI（typer）

```
coder [task]                       # 主入口，等价于 mini
  -m/--model            模型
  -c/--config           配置（YAML + key=value 覆盖）
  --mode                default|acceptEdits|plan|bypass
  --sandbox             local|docker|bubblewrap
  --resume <id>         恢复会话
  --continue            恢复最近会话
  --print               非交互模式，输出到 stdout（供脚本/CI 使用）
  --output-format       text|json|stream-json
```

#### TUI（textual）

`textual` 已在依赖中。TUI 承担：
- 流式渲染 assistant 文本与 reasoning
- 工具调用卡片（折叠、耗时、状态）
- **diff 预览**（编辑类工具执行前展示 unified diff）
- 审批弹窗（显示命令、影响路径、命中规则）
- 状态栏（模型、token 用量、成本、当前目录、权限模式）
- `/` 命令面板

#### Slash 命令

| 命令 | 作用 |
|---|---|
| `/help` | 帮助 |
| `/model` | 切换模型 |
| `/mode` | 切换权限模式 |
| `/plan` | 进入 plan 模式（只读探索，产出计划） |
| `/compact` | 手动压缩上下文 |
| `/clear` | 新会话 |
| `/resume` | 列出并恢复历史会话 |
| `/rewind` | 回滚到检查点 |
| `/init` | 生成项目指令文件 `AGENTS.md` |
| `/diff` | 查看当前改动 |
| `/cost` | 显示用量与成本 |
| `/todos` | 显示任务清单 |
| `/mcp` | 管理 MCP server |

自定义命令：`.coderagent/commands/*.md`，正文中的 `$ARGUMENTS` / `$1` 会被替换。

#### 审批交互

```
╭─ 批准执行 ─────────────────────────────────╮
│ 工具: bash                                  │
│ 命令: rm -rf build/                         │
│ 命中规则: deny → 需要确认                  │
│ cwd: /Users/sailor/project                   │
│                                      [y/n/a] │
╰─────────────────────────────────────────────╯
```
- `y` 本次允许
- `n` 拒绝并把拒绝理由回传给模型
- `a` 总是允许（写入用户级规则文件）

#### Web（FastAPI + SSE）

> 完整设计见 [M5-web-interface.md](milestones/M5-web-interface.md)（为什么这么做）与
> [M5-web-modules.md](milestones/M5-web-modules.md)（哪个函数、什么签名）。

`coder web` 把同一个 agent 放进浏览器：聊天页是终端界面的窗口版，设置页把模型参数配成表单。
**核心一行没改**——web 版需要的四件事核心里已经有了：

| 需要的能力 | 现成的地基 |
|---|---|
| 模型参数可结构化读写 | pydantic `ModelConfig`，`model_kwargs` 直传 litellm |
| 配置分层 | `config/loader.py` 的四层合并 |
| 事件可订阅 | `core/events.py` 的 `EventBus`（TUI 已是它的一个订阅者） |
| 回合可放到别的线程 | 核心全程同步，TUI 已在工作线程里跑 turn |

模块布局（`src/coderagent/web/`）：

```
├── app.py           # create_app(config, cwd, ...) -> FastAPI
├── api.py           # APIRouter(prefix="/api")：全部 REST + SSE 端点
├── sessions.py      # SessionRegistry + SessionRuntime：线程、环形缓冲、turn 执行
├── events.py        # normalize(Event) -> list[item]：核心事件 → 前端条目
├── approver.py      # WebApprover：阻塞式审批，答案由 HTTP 送回
├── config_api.py    # 读写用户级 config.yaml、分层预览、脱敏、连通性测试
├── files.py         # 文件浏览：越界检查、列目录、读文件、diff
├── i18n.py          # 页面语言：地区判定 + 浏览器文案
├── server.py        # serve(cwd, host, port)：uvicorn 入口
├── templates/{en,zh}/  # Jinja2 模板（每种语言一份）
└── static/          # app.css / app.js（原生 JS，无构建步骤）
```

**线程模型**：每会话一个 worker 线程；turn 期间持 `busy` 标志，第二个 `/messages` → **409**。
FastAPI 的事件循环里**绝不**跑 agent 代码——碰文件系统/模型/loop 的端点都写成普通 `def`。
每会话的 `AgentLoop` **懒建**（第一次跑 turn 时才建），否则看一眼会话列表就起一整套 MCP 线程。

**传输**：服务端 → 浏览器用 **SSE**（单向推送、自带重连），浏览器 → 服务端用 **REST**。
不用 WebSocket：没有双向实时需求。SSE 帧是 `data: {json}\n\n`，每 15 秒一个 `: keep-alive`；
一轮结束时发 `turn_end`（命令是 `command_end`），流随之关闭，浏览器拿新的 `since` 重开。

**缓冲与回放**：`/items?since=` 与 SSE **共用一个 `seq` 空间**。环形缓冲（1000 条）里存的是
`normalize()` 之后的条目；**流式的增量（`text_delta` / `reasoning_delta`）是瞬时的**，只推给
正在听的浏览器、**不进缓冲**——否则一轮长回答的 token 会把历史挤出缓冲。整段答案随后以一条
`assistant_message` 进缓冲。

**审批**：`WebApprover` 在 worker 线程上阻塞（`threading.Event` 唤醒），答案由
`POST /api/approvals/{id}` 送回；**没人回答就是拒绝**（超时自动 DENY，与 TUI 一致）。
`Always allow` 会往用户级规则文件写一条规则，前端必须提示这一点。

**模型配置页**：显式字段 + 自由 kwargs，附**分层来源预览**（每个字段来自 `defaults` /
`project` / `user` / `env` 哪一层）与**连通性测试**（一次 `max_tokens=1` 的调用，外加一次
工具调用测试）。密钥只回 `api_key_set` + 掩码，点击才取明文。写入**只落用户级文件**
`~/.coderagent/config.yaml`——**项目级 `.coderagent/config.yaml` 永远不写**（它会进 git）。

**权限的两个入口**：设置页写用户级配置文件的 `permissions:` 段（对**下一个**会话生效），
聊天页的模式下拉框改**当前**会话的 `PermissionPolicy`（**立刻**生效，策略是原地改的）。
`--permission-mode` 钉死的是会话**开始时**的模式，不是锁。

**文件浏览**：目录树 / 读文件 / 工作区 diff 复用现有工具（`list_entries`、`ReadTool`、
`make_diff`），路径安全是三层：`resolve()` → `within_bounds()` → 工具自己的检查。
**不能用 `policy.evaluate("read", ...)` 当边界检查**——`allow` 规则能越过边界，那会把整块磁盘
暴露给浏览器。

**安全模型**：默认只听 `127.0.0.1`；**没有认证**（能访问端口的人就能驱动 agent 在工作目录里
跑 shell，与 `coder` 命令行的信任模型相同）；写接口要求 `X-Coder-Client: 1` 头，跨站浏览器
发不了（`curl` 不受影响）；密钥永不明文出服务器。

**页面语言**：中文地区（CN/HK/MO/TW）默认中文，其余英文；顶栏下拉框与 `?lang=` 的选择优先级
最高，其次是地址所在的地区，最后才是浏览器的 `accept-language`。加一种语言要动三处：
模板目录、`i18n.py` 的 `LANGUAGES`/`STRINGS`、以及 `REGION_LANGUAGES`。

**依赖边界**：`web/__init__.py` 只有 docstring——`import coderagent` **不会**拉起
fastapi / uvicorn / jinja2；`ui/cli.py` 的 `web` 子命令在函数体里惰性导入。

#### Web 版的功能清单

| 功能 | 说明 |
|---|---|
| **聊天页** | 三栏：左栏是会话列表与文件树，中栏是对话，右栏是状态、本轮改过的文件与正在看的文件 |
| **流式输出** | SSE 推送，边生成边显示；断线重连带 `since` 接着看，不会从头再来 |
| **工具卡** | 一次调用一张卡（标题用与 TUI 同一份 `summarize()`），按 `tool_call_id` 更新同一张卡，带输出、报错与 diff |
| **审批卡** | Allow / Deny / Always 三个按钮；**没人回答就是拒绝**（超时自动 DENY） |
| **设置页** | 模型参数写成表单，每个字段下面标着它来自哪一层（`defaults`/`project`/`user`/`env`），底部是脱敏后的分层预览 |
| **连通性测试** | 一次最便宜的调用 + 一次工具调用测试，测通了再保存 |
| **测试模型面板** | 端点 + key + 模型名，不写任何文件，只管试 |
| **权限两个入口** | 设置页写用户级配置（对**下一个**会话生效），聊天页的模式下拉框改**当前**会话（**立刻**生效） |
| **会话管理** | 列表 / 续接 / fork / 回放；回放能看到历史消息与工具的 diff |
| **文件浏览** | 目录树、读文件、工作区 diff；越界一律 **403** |
| **Slash 命令** | 与终端**同一套**（内置命令 + 项目自定义命令），输出走 `command_output` 条目，不混进对话气泡 |
| **中断** | 一键停掉正在跑的那轮 |
| **页面语言** | 中英文；顶栏下拉框切换**不刷新页面**，选择记在浏览器与 cookie 里 |
| **HTTP API** | 页面的每个动作都是普通 HTTP 调用，可以拿脚本驱动；交互式文档在 `/api/docs` |

对外的接口面（`/api` 前缀）：

| 分组 | 端点 |
|---|---|
| 会话 | `GET/POST /api/sessions`、`GET /api/sessions/{id}`、`/events`、`/items?since=`、`/stream?since=`、`/status`、`/metrics`、`/changes`、`POST /resume`、`/fork`、`/messages`、`/interrupt`、`/mode` |
| 审批 | `POST /api/approvals/{id}`（allow / deny / always） |
| 配置 | `GET /api/config`、`GET /api/config/model/key`、`PUT /api/config/model`、`PUT /api/config/permissions`、`POST /api/config/model/test` |
| 文件 | `GET /api/files?path=&depth=`、`GET /api/file?path=`、`GET /api/diff?path=` |
| 其它 | `GET /api/commands`、`GET /api/i18n/{language}`、`GET /lang/{language}` |

状态码是接口契约的一部分：写接口缺 `X-Coder-Client` 头 → **403**；会话正忙 → **409**；
未知会话 / 无人等待的审批 → **404**；空消息 / 非法模式 / 非法审批决策 → **400**；路径越界
→ **403**。

### 4.7 L6 扩展层

#### MCP 客户端

```python
# src/coderagent/tools/mcp.py
class MCPServerConfig(BaseModel):
    name: str
    command: str | None = None          # stdio
    url: str | None = None              # sse / streamable http
    env: dict[str, str] = {}
    enabled: bool = True


class MCPClient:
    """管理到 MCP server 的连接，把 server 暴露的 tool 转成 Tool。"""
    async def connect(self, cfg: MCPServerConfig) -> list[Tool]: ...
    async def disconnect(self) -> None: ...
```

- 传输：stdio（`mcp` python SDK 的 `stdio_client`）、SSE、Streamable HTTP
- 工具命名：`mcp__<server>__<tool>`
- 生命周期：随 Session 创建/销毁；断线自动重连一次
- MCP server 提供的 resources/prompts 作为只读上下文注入

#### Hooks

对齐 Claude Code 的事件点：

| Hook | 时机 | 用途 |
|---|---|---|
| `SessionStart` | 会话开始 | 注入环境信息 |
| `UserPromptSubmit` | 用户输入后、调用模型前 | 校验/改写/拦截输入 |
| `PreToolUse` | 工具执行前 | 拦截/改写/拒绝危险操作 |
| `PostToolUse` | 工具执行后 | 追加反馈、记录审计 |
| `Stop` | agent 想结束时 | 阻止结束、要求继续 |
| `SessionEnd` | 会话结束 | 归档、经验沉淀 |

Hook 本身是「命令 + JSON 输入 → JSON 输出」，用 `subprocess` 执行，零依赖：

```jsonc
// .coderagent/hooks.json
{
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "./scripts/check_secrets.sh"}]
    }
  ]
}
```

#### Subagent（后置）

`task` 工具：主 agent 把一个独立子任务委派给子 agent（独立上下文、独立工具集、可指定模型档位），返回结构化结果。

```python
@dataclass
class SubagentSpec:
    name: str
    description: str
    system_prompt: str
    tools: list[str] = ["read", "grep", "glob", "bash"]
    model_purpose: str = "cheap"
```

子 agent 定义存放在 `.coderagent/agents/*.md`（front-matter + 正文 prompt）。

#### 项目指令文件

按优先级加载并合并：
1. `~/.coderagent/CLAUDE.md`（用户级）
2. 项目根 `AGENTS.md` 或 `CLAUDE.md`
3. 子目录的 `AGENTS.md`（进入该目录时追加加载，Claude Code 风格）

内容注入到 system prompt 的独立区块，标注来源。

---

## 5. 核心接口定义

```python
# src/coderagent/core/protocols.py
from typing import Protocol, Any


class ModelBackend(Protocol):
    """可插拔的后端：litellm / anthropic sdk / 自建网关。"""

    def query(self, messages: list[dict], tools: list[dict] | None = None,
              **kwargs) -> dict: ...

    def query_stream(self, messages: list[dict], tools: list[dict] | None = None,
                     **kwargs) -> Iterator[dict]: ...

    def get_template_vars(self) -> dict[str, Any]: ...


class ToolExecutor(Protocol):
    def plan(self, actions: list[dict]) -> list[dict]:
        """解析 tool_calls → 规范化 action 列表（含 tool_call_id 回填）。"""
    def execute(self, actions: list[dict]) -> list[dict]:
        """执行并返回 observation 消息。"""
```

统一 action 字典格式（跨 Model/Environment/Tool 传递）：

```python
{
    "tool": "edit",              # 工具名
    "tool_call_id": "call_abc",  # 回填给 API
    "args": {"path": "...", "old_string": "...", "new_string": "..."},
    "raw": {...},                # 原始 tool_call
}
```

---

## 6. 目录结构

```
src/coderagent/
├── __init__.py              # 导出 Protocol 与版本
├── core/
│   ├── protocols.py         # ModelBackend / ToolExecutor 协议
│   ├── session.py           # Session, SessionStore, SessionState
│   ├── events.py            # Event, EventBus, 事件类型
│   ├── loop.py              # AgentLoop（多轮主循环）
│   ├── context.py           # ContextEngine（构建 prompt / 压缩）
│   ├── history.py           # 消息历史抽象（按轮切分 / 切分点）
│   ├── tokens.py            # token 估算器
│   ├── budget.py            # BudgetGuard, 输出裁剪
│   ├── summarize.py         # 结构化摘要 schema 与生成
│   ├── instructions.py      # CLAUDE.md / AGENTS.md 加载
│   ├── memory.py            # 分层记忆读写
│   └── checkpoint.py        # 文件树/容器快照与回滚
├── models/
│   ├── gateway.py           # ModelGateway, 用途路由
│   ├── streaming.py         # ModelEvent, 增量 tool_call 拼接
│   ├── router.py            # ModelRouter, 路由规则
│   └── backends.py          # litellm 后端包装
├── tools/
│   ├── base.py              # Tool, ToolResult, ToolContext
│   ├── registry.py          # ToolRegistry（schema 生成 / 预算裁剪）
│   ├── executor.py          # ToolExecutor（解析 → 权限 → 执行）
│   ├── permissions.py       # PermissionMode, Rule, PermissionPolicy, Approver
│   ├── rules.py             # 规则文件加载与合并
│   ├── builtin/{fs,search,shell,web,todo,task}.py
│   └── mcp.py               # MCP 客户端
├── environments/
│   └── local.py, docker.py  # 薄封装，底层复用 minisweagent.environments
├── ui/
│   ├── cli.py               # typer 入口
│   ├── tui.py               # textual App
│   ├── render.py            # 消息/diff 渲染
│   ├── widgets/             # ToolCard, DiffView, ApprovalPrompt, StatusBar...
│   ├── commands/            # slash 命令实现
│   └── custom_commands.py   # .coderagent/commands/*.md 加载
├── extensions/
│   ├── hooks.py             # HookRunner
│   ├── skills.py
│   └── plugins.py
├── web/
│   ├── __init__.py          # 只有 docstring：不 import fastapi（web extra 才是硬依赖）
│   ├── app.py               # create_app：装配 app、静态资源、模板
│   ├── api.py               # 全部 REST + SSE 端点（/api 前缀）
│   ├── sessions.py          # SessionRuntime / SessionRegistry：线程、环形缓冲、turn
│   ├── events.py            # normalize(Event) -> 前端条目
│   ├── approver.py          # WebApprover：阻塞式审批
│   ├── config_api.py        # 配置分层、脱敏、写回、连通性测试
│   ├── files.py             # 文件浏览与 diff（路径越界 403）
│   ├── i18n.py              # 页面语言与地区判定
│   ├── server.py            # serve()：uvicorn 入口
│   ├── templates/{en,zh}/   # Jinja2 模板，每种语言一份
│   └── static/              # app.css / app.js（原生 JS，无构建步骤）
├── config/
│   ├── schema.py            # pydantic 配置模型
│   ├── loader.py            # 四层配置合并
│   └── defaults.yaml
├── testing/
│   └── scripted_model.py    # 脚本化假模型（测试用）
└── run.py                   # 组合装配（类似 mini 的 run/mini.py）
```

---

## 7. 配置设计

沿用 mini 的「YAML + 命令行 key=value 递归合并」，扩展为四层：

```
内置 defaults.yaml  <  项目 .coderagent/config.yaml  <  用户 ~/.coderagent/config.yaml  <  CLI 参数
```

```yaml
# .coderagent/config.yaml
model:
  model_name: anthropic/claude-sonnet-4-5
  routing:
    main: anthropic/claude-sonnet-4-5
    cheap: anthropic/claude-haiku-4-5
    summarize: anthropic/claude-haiku-4-5
  model_kwargs:
    temperature: 0.0
  max_retries: 5

agent:
  mode: default            # default|acceptEdits|plan|bypass
  max_turns: 100
  cost_limit: 5.0
  auto_compact: true
  compact_threshold: 0.8

tools:
  enabled: [read, write, edit, glob, grep, ls, bash, todo_write, web_fetch]
  disabled: []
  bash_timeout: 120
  max_output_tokens: 8000
  include_dirs: []

permissions:
  mode: default
  rules:
    - tool: bash
      pattern: "git status*"
      decision: allow
    - tool: write
      pattern: "/etc/**"
      decision: deny
    - tool: bash
      pattern: "rm -rf*"
      decision: ask

mcp:
  servers:
    - name: filesystem
      command: npx -y @modelcontextprotocol/server-filesystem .

sandbox:
  type: local              # local|swerex_docker|bubblewrap|contree
  # 其余选项原样传给环境（如 docker 的 run_args、image）
```

### 7.1 谁可以写配置

| 写入方 | 写哪一层 | 生效时机 |
|---|---|---|
| CLI `-c key=value` | 内存（最高优先级） | 当次运行 |
| Web 设置页 | **只写用户级** `~/.coderagent/config.yaml` | **下一个**会话 |
| 项目级 `.coderagent/config.yaml` | **任何自动流程都不写**（会进 git） | — |

Web 设置页是**合并**而不是覆盖：读现有 YAML → 只改用户提交的子键 → 写回，未知的顶层段
（`agent:` / `tools:` / `mcp:`…）与未知的 `model:` 子键原样保留。已知代价：注释会丢
（用 `yaml.safe_dump`，不引 ruamel）。

### 7.2 api key 的来源顺序

```
model.model_kwargs.api_key  >  别名文件 litellm_params.api_key  >  厂商的环境变量
```

（`openai/…` → `OPENAI_API_KEY`，`deepseek/…` → `DEEPSEEK_API_KEY`，其余同理。）
设置页读到的也是这个顺序，`sources.api_key` 会报出它来自哪一层；密钥永不明文出服务器。

---

## 8. 关键设计决策

| # | 决策 | 备选 | 选择理由 |
|---|---|---|---|
| 1 | 保留 bash 作为一等工具，同时新增专用工具 | 仅 bash / 仅专用工具 | 专用工具精确（edit 的唯一匹配约束），bash 兜底覆盖长尾；与 Claude Code 一致 |
| 2 | Session / Run 分离 + 事件溯源 JSONL | 直接沿用 mini 的 `run()` 循环 | 支持 resume/fork/审计/崩溃恢复 |
| 3 | 上下文压缩产出**结构化摘要**而非自由文本 | 自由文本摘要 | 保住「改了哪些文件、还剩什么问题」，模型不丢失任务状态 |
| 4 | 工具结果按 **token 预算**裁剪，非固定字符 | mini 的固定 10000 字符 | 不同模型 token/char 比例差异大，字符裁剪易溢出 |
| 5 | 权限规则用 **glob/regex 匹配 + 决策枚举** | 黑白名单 | 需要 ask 这一中间态，且要能解释「为什么被拦」 |
| 6 | 工具描述按上下文预算动态裁剪 | 全量发送 | 工具多时 tool schema 本身可能占 10k+ token |
| 7 | Hooks 用「子进程 + JSON」的 Claude Code 兼容格式 | 自定义 Python 插件 | 零依赖、跨语言、易于用户编写 |
| 8 | MCP 工具统一命名 `mcp__server__tool` | 服务端原名 | 避免与内置工具冲突，与 Claude Code 生态兼容 |
| 9 | 独立顶层包 `src/coderagent/`，而非 `minisweagent/coder/` | 嵌套 | 保持上游仓库干净，日后可独立拆仓；同时需改 pyproject 的 packages.find |
| 10 | 子 Agent 后置到 M3 | 首版实现 | 复杂度高、收益依赖模型能力；先把主循环与上下文治理做扎实 |
| 11 | Web 版**不改核心**，只做另一个事件订阅者 | 为 web 重写一套循环 | 会话/工具/权限/事件日志全复用；浏览器里开的会话能用 `coder --resume` 在终端接着聊 |
| 12 | 服务端 → 浏览器用 **SSE** | WebSocket | 单向推送、自带重连、心跳现成；没有双向实时需求，少一个协议少一份状态 |
| 13 | 写接口要 `X-Coder-Client: 1` 头 | token 认证 / 同源检查 | 跨站浏览器发不出这个头（要先过预检，而服务端不给许可）；`curl` 不受影响，零配置 |
| 14 | 流式增量**不进**环形缓冲 | 全进缓冲 | 逐 token 的增量一轮能有几百条，会把历史挤出缓冲；整段答案随后以一条 `assistant_message` 进缓冲 |
| 15 | 配置**只写用户级文件** | 也允许写项目级 | 项目级 `.coderagent/config.yaml` 会进 git，密钥不能进仓库 |
| 16 | 路径边界用 `within_bounds()` | `policy.evaluate("read", …)` | `allow` 规则能越过边界检查，那等于把整块磁盘暴露给浏览器 |
| 17 | 权限分两层：设置页（新会话）+ 聊天页（立刻） | 只有设置页 | 运行中的会话要能立刻换模式，否则无人值守跑法很别扭 |
| 18 | 启动时的 `--permission-mode` 钉的是**会话开始时的模式**，不是锁 | 锁死模式 | 聊天页换模式是「当着会话的面做的决定」，不是文件里的设置 |
| 19 | Web 版**没有认证**，文档里明说 | 加个 token | 单用户本机工具，信任模型同 `coder` 命令行；加 token 反而挡了脚本化调用 |

---

## 9. 分阶段路线图（细化版）

各里程碑的**逐条任务分解、接口定义、验收标准、测试计划、风险对策**见独立文档：

| 里程碑 | 文档 | 主题 | 预估 |
|---|---|---|---|
| M0 | [M0-skeleton.md](milestones/M0-skeleton.md) | 骨架与配置：Session / EventBus / Loop / Config | 1 周 |
| M1 | [M1-tools-permissions.md](milestones/M1-tools-permissions.md) | 工具系统与权限：ToolRegistry / PermissionPolicy | 2 周 |
| M2 | [M2-context-session.md](milestones/M2-context-session.md) | 上下文治理与会话管理：压缩 / 恢复 / 检查点 | 2 周 |
| M3 | [M3-ui-extensions.md](milestones/M3-ui-extensions.md) | 交互体验与扩展：TUI / MCP / Hooks / 命令 | 2 周 |
| M4 | [M4-advanced.md](milestones/M4-advanced.md) | 进阶能力：子 Agent / 路由 / 记忆 / 插件 | 按需 |
| M5 | [M5-web-interface.md](milestones/M5-web-interface.md) · [M5-web-modules.md](milestones/M5-web-modules.md) | Web 版：FastAPI 应用 / SSE 事件流 / 审批 / 配置页 / 文件浏览 | 1 周 |

### 9.1 里程碑依赖图

```
        ┌─────────────┐
        │ M0 骨架/配置│
        └──────┬──────┘
               │ EventBus / Session / Config / Loop
        ┌──────▼──────┐
        │ M1 工具/权限│
        └──────┬──────┘
               │ ToolRegistry / Policy / Executor
        ┌──────▼──────┐
        │ M2 上下文/会话│
        └──────┬──────┘
               │ ContextEngine / Checkpoint / Command
        ┌──────▼──────┐
        │ M3 UI/扩展   │
        └──────┬──────┘
               │ TUI / MCP / Hooks
        ┌──────▼──────┐
        │ M4 进阶能力  │
        └──────┬──────┘
               │ Subagent / Router / Skills / Plugins
        ┌──────▼──────┐
        │ M5 Web 版   │
        └─────────────┘
```

**硬依赖**：M1 需要 M0 的 EventBus（工具事件）与 Session（todo 状态）；M2 需要 M1 的工具输出形态（裁剪对象）；M3 需要 M2 的 `ContextEngine`（状态栏 token 用量）与命令实现。
**软依赖**：M4 各特性彼此独立，可单独交付。
**M5 不依赖任何新能力**：它只用 M0–M4 已经有的地基（EventBus 订阅、四层配置、工具、slash 命令），
所以可以独立交付；反过来它对核心的改动都是**加法**（见 §12 的改动表）。

### 9.2 各里程碑的核心交付物与出口条件

**M0 — 骨架与配置**
- 交付：`core/{protocols,events,session,loop}.py`、`models/gateway.py`、`config/{schema,loader,defaults.yaml}`、`ui/{cli,render}.py`、`run.py`、`testing/scripted_model.py`
- 出口：`coder --print --output-format json` 能完成多轮对话并落盘 JSONL 轨迹；`--continue` 可恢复

**M1 — 工具系统与权限**
- 交付：`tools/{base,registry,executor,permissions,rules}.py`、`tools/builtin/{fs,search,shell,todo}.py`
- 出口：模型能完成「读 → 定位 → 编辑 → 验证」的跨文件任务且文件真实变更；危险命令被正确拦截；headless 遇 `ask` 不挂起

**M2 — 上下文治理与会话管理**
- 交付：`core/{tokens,budget,history,context,summarize,instructions,memory,checkpoint}.py`
- 出口：200 轮模拟会话不超预算；压缩后模型仍说得清「改了哪些文件、还剩什么问题」；超限异常被自动兜底

**M3 — 交互体验与扩展**
- 交付：`ui/tui.py` + `ui/widgets/*`、`ui/commands/*`、`models/streaming.py`、`tools/mcp.py`、`extensions/hooks.py`
- 出口：TUI 中可见流式输出、diff 预览、审批弹窗；能加载真实 MCP server；hook 能拦截并改写工具参数

**M4 — 进阶能力**
- 交付：`tools/builtin/task.py`、`models/router.py`、`extensions/{skills,plugins}.py`
- 出口：`task` 委派不污染主上下文；路由能按上下文长度与预算升降档；`coder export` 输出完整 trace

**M5 — Web 版**
- 交付：`web/{app,api,sessions,events,approver,config_api,files,i18n,server}.py`、`web/templates/{en,zh}/`、`web/static/`，以及 `coder web` 子命令
- 出口：浏览器里能完整跑一轮（发消息 → 流式输出 → 触发审批 → 允许 → 看工具卡与 diff）；`/settings` 能改模型参数并测试连通性，只写用户级文件；权限两个入口都生效（设置页对新会话、聊天页对运行中的会话）；文件树能浏览、读文件、看 diff，越界 403；会话能列表 / 续接 / fork；`pytest tests/coderagent -q` 全绿且 `mkdocs build --strict` 无警告

### 9.3 跨里程碑接口契约

以下接口在引入后**不再变更**，后续里程碑只能扩展不能改语义：

| 契约 | 引入于 | 约束 |
|---|---|---|
| `Event` / `EventBus` | M0 | 字段只增不改；未知事件类型 `rebuild` 时跳过 |
| `Session` / `SessionStore` | M0 | JSONL 追加写；`rebuild` 幂等 |
| `Tool` / `ToolResult` / `ToolContext` | M1 | 工具失败返回 `is_error=True`，不抛异常 |
| `PermissionPolicy.check` | M1 | 返回 `allow`/`ask`/`deny` 三态；规则「后写覆盖」 |
| `ToolExecutor.execute` | M1 | 返回顺序必须与输入 tool_call 顺序一致 |
| `ContextEngine.build_messages` | M2 | 消息顺序固定：system → instructions → summary → history |
| `ModelGateway.query_stream` | M3 | 产出 `ModelEvent` 序列；工具调用在 `tool_call_done` 时完整 |
| `HookRunner.run` | M3 | 异常 / 超时不得阻断主流程（除非 `strict`） |
| `web.events.normalize` | M5 | 核心事件 → 前端条目的**唯一**翻译层；未知事件类型返回空列表，不抛异常 |
| `SessionRuntime.emit` / `attach` / `detach` | M5 | 缓冲与 SSE 共用同一个 `seq` 空间；瞬时条目只推不存 |
| `PermissionPolicy.within_bounds` | M5 | 路径越界检查**不被规则放宽**；越界 → 403 |

### 9.4 全局 Definition of Done

每个里程碑完成时，以下条目全部满足才算交付：

- [ ] 该里程碑的「出口条件」全部达成
- [ ] 新增功能有对应单测，且失败路径（错误、超时、边界）被覆盖
- [ ] 未引入对 `minisweagent` 内部实现的依赖（只用公开 API）
- [ ] ruff / pre-commit 通过
- [ ] headless 与 TUI 行为一致（同一 trace 可复现）
- [ ] 里程碑文档中的任务清单全部勾选

---

## 10. 全局测试策略

沿用 mini 的 pytest 风格，**不 mock 未被显式要求的东西**。可测边界靠协议解耦获得：

| 层 | 测试方式 | 代表用例 |
|---|---|---|
| 工具层 | 真实文件系统（tmp_path） | `edit` 唯一匹配失败、旧内容不存在、路径越界 |
| 权限层 | 纯函数 | 规则优先级 deny>ask>allow、glob 匹配边界 |
| 压缩层 | 假 model 返回固定摘要 | 保留窗口不被压缩、摘要字段完整注入 |
| 会话层 | 真实 JSONL 文件 | 中断后 resume 状态一致、事件顺序单调 |
| 端到端 | 假 model（脚本化响应序列）+ 真实 env | 多轮收敛、工具并行顺序正确 |
| Web 层 | `TestClient` + `ScriptedModel` + 真实 tmp 文件系统 | 写接口缺客户端头 403、会话忙 409、路径越界 403、密钥不明文、项目级配置永不被写、审批超时自动 DENY |

Web 层的测试在 `tests/coderagent/web/`：`fastapi` 是**可选依赖**，测试文件首行
`pytest.importorskip("fastapi")`；`MSWEA_CODER_HOME` 被全局 fixture 指向 tmp → 隔离。
**所有 web 代码必须在调用时读 `config_home()`，不能 import 时缓存**。

关键：**造一个 `ScriptedModel`**，按序返回预置响应，用于不依赖真实 API 的全链路测试（这是让 CI 可跑的前提）。

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 专用工具与 bash 语义重叠，模型困惑 | 质量下降 | 工具描述明确边界；edit 失败时提示改用 bash；prompt 中给使用建议 |
| 结构化摘要丢失关键信息 | 长会话跑偏 | 摘要 schema 强制字段 + 每次压缩后校验「files_touched」非空 |
| 上下文估算不准（tokenizer 差异） | 仍会 OOM | 预留 15% 余量 + 超限异常兜底触发强制压缩 |
| TUI 与 headless 行为分叉 | 线上问题难复现 | 核心逻辑（loop/context/tools）与 UI 完全解耦，headless 为准 |
| 权限规则误伤 | 体验差 | 提供 `/permissions` 查看命中规则与来源；拒绝时回传原因让模型改写 |
| 上游 mini-swe-agent 演进冲突 | 维护成本 | `coderagent` 只依赖 `minisweagent` 的稳定公共 API（Protocol/配置/环境），版本化锁定 |
| Web 版**没有认证**，能访问端口就能驱动 agent | 高 | 默认只听 `127.0.0.1`；`--host` 非回环时打印警告；文档明写信任模型同 `coder` 命令行 |
| 每会话一个 `AgentLoop` ⇒ 每会话一套 MCP server 线程 | 中 | loop 懒建（第一次跑 turn 才建）；会话多了仍会涨，文档说明 |
| 跨站请求驱动 agent（CSRF） | 中 | 写接口要 `X-Coder-Client: 1` 头，跨站浏览器发不出（预检不通过） |
| 浏览器读到工作目录外的东西 | 中 | `resolve()` + `within_bounds()`，越界 403；**边界检查不被规则放宽** |
| 密钥泄漏到仓库或日志 | 高 | 只写用户级文件；API 只回掩码；分层预览里的密钥全抹成 `***` |

---

## 12. 与 mini-swe-agent 的依赖边界

允许依赖的公共面（视为稳定契约）：
- `minisweagent.Model` / `Environment` / `Agent` Protocol
- `minisweagent.config.get_config_from_spec` / `builtin_config_dir`
- `minisweagent.environments.{local,docker,singularity}` 及 `extra/*`
- `minisweagent.models.utils.{retry,cache_control,actions_toolcall}`
- `minisweagent.exceptions`

**不**依赖其内部实现（`agents/default.py` 的循环、`agents/interactive.py` 的审批逻辑），这两处在本项目中重写。

在 `pyproject.toml` 中调整打包：

```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["minisweagent*", "coderagent*"]
```

新增入口：

```toml
[project.scripts]
coder = "coderagent.ui.cli:app"
```

Web 版是**可选依赖**（`import coderagent` 不该拉起 fastapi）：

```toml
[project.optional-dependencies]
web = ["fastapi", "uvicorn", "jinja2"]
```

### 12.1 M5 对既有文件的改动（全部是加法）

| 文件 | 改动 |
|---|---|
| `tools/executor.py` | `_publish` 里把带 diff 的 `TOOL_RESULT` 也写进事件日志（回放才看得到 diff） |
| `tools/permissions.py` | `_within_bounds` → 公开的 `within_bounds` |
| `tools/builtin/search.py` | `LsTool.run` 的遍历逻辑抽成公开 `list_entries`（行为不变） |
| `ui/commands/__init__.py` | `register()` 按名字去重（每会话一个 loop，否则全局命令表无限膨胀） |
| `ui/cli.py` | 新增 `web` 子命令（函数内惰性导入） |
| `config/loader.py` | 抽出 `config_layers(cwd)`，`load_config` 复用它 |
| `run.py` / `testing/factory.py` | 把 `store` 传给 `ToolExecutor` |
| `pyproject.toml` | `web` extra + package-data（模板与静态文件） |
