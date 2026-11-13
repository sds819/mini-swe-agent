# M3 — 交互体验与扩展

> 目标：从「能跑」到「好用」——TUI 实时渲染、diff 预览、审批弹窗、MCP 工具、Hooks、自定义命令。
> 依赖：M0（EventBus/Session）、M1（Tool/Registry/Policy）、M2（Context/Checkpoint）。
> 后续解锁：M4（子 Agent、Skills、插件）。

---

## 1. 交付物清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `src/coderagent/ui/tui.py` | textual App 主界面 |
| 新增 | `src/coderagent/ui/widgets/` | `MessageBlock` `ToolCard` `DiffView` `ApprovalPrompt` `StatusBar` `TodoPanel` |
| 新增 | `src/coderagent/ui/commands/__init__.py` | 命令注册表与分发 |
| 新增 | `src/coderagent/ui/commands/*.py` | 各 slash 命令实现 |
| 新增 | `src/coderagent/ui/custom_commands.py` | 自定义命令加载（`.coderagent/commands/*.md`） |
| 新增 | `src/coderagent/models/streaming.py` | 流式事件模型与增量 tool_call 拼接 |
| 修改 | `src/coderagent/models/gateway.py` | 接入流式查询 |
| 新增 | `src/coderagent/tools/mcp.py` | MCP 客户端与工具桥接 |
| 新增 | `src/coderagent/extensions/hooks.py` | Hook 加载与执行 |
| 新增 | `src/coderagent/extensions/__init__.py` | 扩展注册表 |
| 修改 | `src/coderagent/config/schema.py` | `mcp`、`hooks`、`ui` 配置 |
| 新增 | `tests/coderagent/ui/test_*.py`、`tests/coderagent/tools/test_mcp.py`、`tests/coderagent/extensions/test_hooks.py` | 单测 |

---

## 2. 流式模型层

### 2.1 流式事件

```python
# src/coderagent/models/streaming.py
@dataclass
class ModelEvent:
    type: str          # text | reasoning | tool_call_delta | tool_call_done | usage | error
    content: str = ""
    tool_call: dict | None = None
    cost: float = 0.0
    raw: dict = field(default_factory=dict)
```

### 2.2 增量 tool_call 拼接

流式下 `tool_call` 分片到达，`arguments` 是 JSON 片段，需要拼接后再解析：

```python
class ToolCallAccumulator:
    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}

    def feed(self, delta: dict) -> None:
        idx = delta.get("index", 0)
        call = self._calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        call["id"] = delta["id"] if delta.get("id") else call["id"]
        fn = delta.get("function") or {}
        call["name"] = self._merge_name(call["name"], fn.get("name") or "")
        call["arguments"] += fn.get("arguments", "") or ""

    def finish(self) -> list[dict]:
        """返回解析好的 tool_calls；JSON 非法时抛 FormatError（沿用 minisweagent.exceptions）。"""
```

**注意**：`name` 字段在部分供应商的流式里只在首片出现，部分逐片重复 → 必须**只追加不重复**。实现上不是无脑 `+=`，而是 `_merge_name()`：新片段等于已有名字就跳过，已有名字以新片段开头也跳过。测试需覆盖两种供应商行为。

### 2.3 网关流式接口

```python
class ModelGateway:
    def query_stream(self, messages: list[dict], *, purpose: str = "main",
                     tools: list[dict] | None = None) -> Iterator[ModelEvent]: ...
    def query(self, messages: list[dict], *, purpose: str = "main",
              tools: list[dict] | None = None) -> dict:
        """非流式便捷方法，内部消费流式结果。"""
```

**reasoning 处理**：`reasoning` 事件单独累积，不混入 `text`；写入消息的 `extra.reasoning` 字段，供 UI 折叠显示，也供保存轨迹。

---

## 3. TUI 设计

### 3.1 布局（textual）

```
┌────────────────────────────────────────────────────────────┐
│ StatusBar: model | tokens 12.4k/200k | $0.31 | ⏻ default │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ▌ User                                                     │
│    修复登录超时 bug                                          │
│                                                            │
│  ▌ Assistant                                                │
│    ▸ reasoning (folded)                                     │
│    我先看一下 auth 模块...                                   │
│                                                            │
│  ▌ Tool: read (src/auth.py)  ✓ 42ms                        │
│    ▸ [12 lines]                                             │
│                                                            │
│  ▌ Tool: edit (src/auth.py)  ✓ 18ms                       │
│    ▸ DiffView: +2 -1                                         │
│                                                            │
│  ▌ Todo                                                     │
│    ◐ 定位超时逻辑        (in_progress)                      │
│    ○ 修复并补测                                            │
│                                                            │
├────────────────────────────────────────────────────────────┤
│ > 输入消息…  (/help 查看命令)                                │
└────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责

| 组件 | 职责 | 关键点 |
|---|---|---|
| `StatusBar` | 模型、token 用量、成本、cwd、权限模式 | token 用量来自 `ContextEngine` 估算 |
| `MessageBlock` | 渲染 user / assistant / error 消息 | assistant 的 reasoning 默认折叠 |
| `ToolCard` | 工具调用卡片 | 状态图标（运行中/成功/失败）、耗时、参数摘要、结果折叠 |
| `DiffView` | unified diff 渲染 | 编辑类工具执行后自动展开，可折叠 |
| `ApprovalPrompt` | 审批弹窗 | 显示命令/路径、命中规则与原因、y/n/a 选项 |
| `TodoPanel` | 任务清单 | 订阅 `TOOL_RESULT` 中的 todo 变更 |

> todo 的三个符号是 `◉` = 完成、`◐` = 进行中、`○` = 待办（`ui/widgets/todo_panel.py` 的 `MARKS`）。

### 3.3 事件订阅

TUI 通过 `EventBus` 订阅，与核心逻辑完全解耦：

```
EventBus.subscribe(ASSISTANT_MESSAGE, ...)  → MessageBlock
EventBus.subscribe(REASONING, ...)          → 折叠的 reasoning 区
EventBus.subscribe(TOOL_CALL, ...)          → ToolCard 创建
EventBus.subscribe(TOOL_RESULT, ...)        → ToolCard 更新
EventBus.subscribe(APPROVAL_REQUEST, ...)   → ApprovalPrompt 阻塞等待
EventBus.subscribe(STATE_CHANGE, ...)       → StatusBar 更新
```

**关键约束**：`APPROVAL_REQUEST` 的处理是**阻塞**的（模型执行流要停下等用户）。textual 中通过 `run_worker` + `Future` 实现，不要阻塞 UI 线程。

### 3.4 Diff 预览

- 编辑类工具（`write`/`edit`/`multi_edit`）执行**前**在弹窗中展示 diff（Claude Code 风格）
- 执行**后**在 `ToolCard` 中展示结果 diff
- diff 生成：内置最小实现（`difflib.unified_diff`），不引入外部依赖
- 颜色：新增绿、删除红

### 3.5 Slash 命令体系

**内置命令**

| 命令 | 作用 |
|---|---|
| `/help` | 帮助 |
| `/model` | 切换模型（列出可用 routing 档位） |
| `/mode` | 切换权限模式（default/acceptEdits/plan/readonly/bypass） |
| `/plan` | 切到 plan 模式（只读探索，产出计划） |
| `/compact` | 手动压缩上下文 |
| `/clear` | 开始新会话 |
| `/resume` | 列出并恢复历史会话 |
| `/fork` | 从当前点分叉会话 |
| `/rewind` | 回滚到检查点 |
| `/diff` | 查看当前工作区改动 |
| `/init` | 生成项目指令文件 `AGENTS.md` |
| `/cost` | 用量与成本明细 |
| `/todos` | 当前任务清单 |
| `/mcp` | MCP server 管理（列表/连接状态/启停） |
| `/permissions` | 查看当前生效的权限规则与命中记录 |
| `/hooks` | 查看已加载的 hooks |

> 这 16 个是 M3 当时设计的命令。**今天一共 25 个**：后面 M4 加了 `/agents` `/skills`
> `/plugins` `/memory`，M5 加了 `/status` `/sandbox` `/export` `/context` `/exit`。

**命令注册**

```python
# src/coderagent/ui/commands/__init__.py
@dataclass
class Command:
    name: str
    description: str
    handler: Callable[[CommandContext, str], None]
    aliases: list[str] = field(default_factory=list)


COMMANDS: list[Command] = [...]
```

`CommandContext` 暴露 session / bus / model / policy / loop / store，让命令能操作核心对象。

**自定义命令**

`.coderagent/commands/<name>.md`：

```markdown
---
description: 生成提交信息
argument-hint: [文件路径]
allowed-tools: bash(git diff:*), read
---
分析以下文件的改动并生成一条 Conventional Commit 信息：

$ARGUMENTS
```

- `$ARGUMENTS` → 用户输入的全部参数
- `$1` `$2` → 分开的参数
- front-matter 支持 `description` `argument-hint` `allowed-tools` `model`
- `allowed-tools` 限制该命令运行时的工具集（临时构造受限 Registry）

---

## 4. MCP 集成

### 4.1 配置

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx -y @modelcontextprotocol/server-filesystem ${workspace}
      env: {}
    - name: remote
      url: https://example.com/mcp
      headers: {}
  timeout: 30
```

### 4.2 客户端

```python
# src/coderagent/tools/mcp.py
class MCPServerConfig(BaseModel):
    name: str
    command: str | None = None
    url: str | None = None
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    enabled: bool = True


class MCPClient:
    """管理到 MCP server 的连接，把 server 暴露的 tool 转成 coderagent 的 Tool。"""

    def __init__(self, config: MCPServerConfig, bus: EventBus): ...
    async def connect(self) -> list[Tool]: ...
    async def disconnect(self) -> None: ...
    async def call(self, tool_name: str, arguments: dict) -> ToolResult: ...
```

**要点**

- 传输：优先 **stdio**（`mcp` SDK 的 `stdio_client`）；SSE / Streamable HTTP 次之（M3 先只做 stdio，接口预留）
- 工具命名：`mcp__<server>__<tool>`，与内置工具不冲突
- 工具 schema 直接取 MCP 的 `inputSchema`，包成 OpenAI function 格式
- 内容回填：MCP 的 `content` 数组（text/image/resource）转成字符串或结构化观测
- 生命周期：Session 创建时连接、销毁时断开；断线重连一次，失败则该 server 工具从 Registry 移除并通知用户
- **MCP 工具同样走权限层**：默认 `ask`（因为是外部代码）；可在规则里放行

### 4.3 MCP resources / prompts

**没有实现。** MCP server 暴露的 **resources** 与 **prompts** 都不支持：客户端只拉工具列表
（`list_tools`），不拉资源，也不提供 `/<server>:<prompt>` 这样的调用。

> 这是 M3 的设计稿里列过、但最终没做的两项。

---

## 5. Hooks

### 5.1 事件点

| Hook | 时机 | 输入 | 可用输出 |
|---|---|---|---|
| `SessionStart` | 会话开始 | session 信息 | `additionalContext` |
| `UserPromptSubmit` | 用户输入后、调模型前 | prompt | `additionalContext`、`decision: "block"` + `reason` |
| `PreToolUse` | 工具执行前 | tool + params | `decision: "allow"/"deny"`、`updatedInput`、`additionalContext` |
| `PostToolUse` | 工具执行后 | tool + params + result | `additionalContext`、`decision: "block"` |
| `Stop` | agent 想结束时 | 最后一条消息 | `decision: "block"` + `reason`（要求继续） |
| `SessionEnd` | 会话结束 | 统计信息 | （无） |

### 5.2 配置

hooks 配在**用户级或项目级的 YAML 配置**里（`config.yaml` 的 `hooks.events` 段），
**没有** `.coderagent/hooks.json` 这种单独的 JSON 文件：

```yaml
hooks:
  events:
    PreToolUse:
      - matcher: bash
        hooks:
          - type: command
            command: ./scripts/guard.sh
            timeout: 10
    PostToolUse:
      - matcher: edit|write
        hooks:
          - type: command
            command: ruff format {file}
```

- `matcher` 是工具名的正则（空 = 全部），用 `re.search` 匹配
- **匹配的是模型写下的那个工具名**：工具叫 `bash`、`edit`、`write`，所以写 `"Bash"`
  或 `"Edit"` 匹配不上（大小写敏感）
- `command` 通过 `subprocess.run` 执行（shell=True，cwd = session cwd）
- **stdin 传 JSON**，stdout 读 JSON
- 超时默认 10s，超时视为「无输出」（放行）而不是失败

### 5.3 执行语义

```python
# src/coderagent/extensions/hooks.py
@dataclass
class HookResult:
    decision: str = ""            # allow | deny | block
    reason: str = ""
    additional_context: str = ""
    updated_input: dict | None = None


class HookRunner:
    def __init__(self, config: HookConfig, cwd: Path): ...
    def run(self, hook_name: str, payload: dict) -> list[HookResult]:
        """执行所有匹配 hook，合并结果。"""
```

**合并规则**

- `decision=deny/block` → 阻断并把 `reason` 作为工具错误回传给模型
- 多个 hook → 任一 deny 则 deny；`additional_context` 拼接
- Hook 自身抛异常/非零退出 → 记录日志，不阻断（除非配置 `strict: true`）

**PreToolUse 顺序**：在 `ToolExecutor` 中，**权限检查之前**执行 Hook → Hook 可改写参数（`updatedInput`）→ 再走权限检查。这样「Hook 改写后的命令」才是被审批的对象。

---

## 6. 任务分解

### T6.1 流式模型层
- [x] `ModelEvent` 定义
- [x] `ToolCallAccumulator`（含「name 重复片」处理）
- [x] `ModelGateway.query_stream` 接 litellm `stream=True`
- [x] `query` 改为消费流式结果
- [x] reasoning 事件累积

**验收**：`test_streaming.py` — 模拟多片 tool_call 拼接正确；非法 JSON 抛 `FormatError`。

### T6.2 TUI 骨架
- [x] textual App 布局（StatusBar / 消息区 / 输入区）
- [x] 事件订阅接线
- [x] 输入框提交 → `AgentLoop.run_turn`
- [x] Ctrl-C 中断当前 turn（`InterruptAgentFlow` 语义）

**验收**：`test_tui.py`（用 textual 的 `run_test()`）——发送一条消息后能观察到 assistant 消息块出现。

### T6.3 消息与工具卡片
- [x] `MessageBlock`（user/assistant/error）
- [x] reasoning 折叠
- [x] `ToolCard`（状态、耗时、参数摘要、结果折叠）
- [x] 长输出折叠 + 展开

### T6.4 Diff 预览
- [x] `difflib` 生成 unified diff
- [x] `DiffView` 渲染（颜色、折叠）
- [x] 执行前展示（与审批弹窗合并）

### T6.5 审批弹窗
- [x] `ApprovalPrompt`（工具、参数、命中规则、原因）
- [x] `y` / `n` / `a` 三选项
- [x] 拒绝时把理由作为工具错误回传
- [x] `a` → 写入用户级规则文件

### T6.6 状态栏与 Todo 面板
- [x] `StatusBar`：模型、token、成本、cwd、权限模式
- [x] `TodoPanel`：订阅 todo 变更

### T6.7 Slash 命令框架
- [x] `Command` dataclass + 注册表 + 分发
- [x] 输入框识别 `/` 开头 → 命令分发（否则视为普通消息）
- [x] 内置命令全部实现（M0/M1/M2 已实现的逻辑接进来）

### T6.8 自定义命令
- [x] 加载 `.coderagent/commands/*.md`
- [x] front-matter 解析（`description` `argument-hint` `allowed-tools` `model`）
- [x] `$ARGUMENTS` / `$1` 替换
- [x] `allowed-tools` 构造受限 Registry

### T6.9 MCP 客户端
- [x] `MCPServerConfig`、配置加载
- [x] stdio 传输连接
- [x] tool 列表拉取 → 转成 `Tool` → 注册（`mcp__server__tool`）
- [x] 调用与结果回填
- [x] 断线重连一次
- [x] MCP 工具走权限层

### T6.10 Hooks
- [x] `HookConfig` / `HookRunner`
- [x] 六个事件点接入
- [x] `PreToolUse` 改写参数 → 再走权限检查
- [x] `Stop` 的 block 语义（要求 agent 继续）

### T6.11 配置扩展
- [x] `MCPConfig`、`HookConfig`、`UIConfig`

### T6.12 文档
- [x] `docs/usage/` 补充 MCP、Hooks、自定义命令说明

---

## 7. 测试计划

| 文件 | 覆盖点 |
|---|---|
| `models/test_streaming.py` | 增量拼接、name 重复片、非法 JSON |
| `ui/test_tui.py` | textual `run_test()` 驱动：消息渲染、命令分发 |
| `ui/test_commands.py` | 内置命令的注册与基本行为（当时 18 个，今天 25 个） |
| `ui/test_custom_commands.py` | front-matter 解析、参数替换、工具限制 |
| `tools/test_mcp.py` | 用一个本地 echo MCP server 做 stdio 集成测试 |
| `extensions/test_hooks.py` | allow/deny/block、改写参数、超时、异常隔离 |

> MCP 集成测试可用 `mcp` SDK 自带的示例 server，或写一个 30 行的 stdio server 作为 fixture（不 mock 协议层）。

---

## 8. 风险

| 风险 | 对策 |
|---|---|
| textual 事件循环与阻塞式 AgentLoop 冲突 | AgentLoop 跑在 worker 线程/协程中；UI 只通过 EventBus 被动渲染 |
| 流式 tool_call 参数拼接在多供应商行为不一致 | `ToolCallAccumulator` 对「name 重复」与「arguments 分片」都做防御性处理，双路径单测 |
| MCP 引入额外依赖（`mcp` 包） | 设为可选 extras（`pip install coderagent[mcp]`），未安装时功能优雅降级 |
| Hooks 阻塞主流程 | 硬超时（默认 10s）；超时视为放行；`strict` 模式可选 |
| TUI 与 headless 行为分叉 | 核心逻辑只走 `EventBus`；headless 模式订阅一个「打印型」订阅者 |

---

## 9. Definition of Done

- [x] TUI 中能看到流式输出、工具卡片、diff、审批弹窗、状态栏
- [x] 至少 18 个内置 slash 命令可用（M3 交付时 19 个，今天 25 个）
- [x] 自定义命令（`.md`）能运行并限制工具集
- [x] 至少一个真实 MCP server 的工具可在会话中调用
- [x] `PreToolUse` hook 能拦截工具调用并改写参数
- [x] headless 模式行为与 TUI 一致（同一 trace）

---

## 10. 实现说明（与原设计的偏差）

| 项 | 设计 | 实现 | 原因 |
|---|---|---|---|
| 流式接口 | `ModelGateway.query_stream` | 后端与网关都有 `query_stream`；`query` 由流折叠而来 | 网关要记账（成本/调用次数），折叠只有一处实现 |
| 增量事件 | 事件写入 event log | `TEXT_DELTA` / `REASONING` 只走 `EventBus`，不写日志 | 日志是「事实」，一个字一个字记会把它撑爆 |
| TUI 并发模型 | AgentLoop 跑在协程里 | AgentLoop 保持同步，跑在 textual 的 worker 线程里 | 核心不引入异步依赖；界面线程通过 `call_from_thread` 更新 |
| 组件实现 | 每个组件一个容器 + 子组件 | `MessageBlock` / `ToolCard` 是 `Static`，用 `render()` 画 | `compose()` 是异步的，流式文本会在 compose 之前到达；`render()` 没有这个时序问题 |
| reasoning 折叠 | 可展开的折叠区 | 折叠成一行暗色文字 | 同上：单行渲染无法再挂子组件 |
| 长输出折叠 | 可展开 | 前 8 行 + 「▸ N more lines」 | 同上；折叠区要 compose，无法在流式刷新时安全挂载 |
| Diff 展示 | 执行前在弹窗里，执行后在卡片里 | 同左 | 弹窗里的 diff 由 `prospective_diff()` 在执行前算出来 |
| 审批 | 弹窗阻塞等待 | `TUIAprover` 发 `APPROVAL_REQUEST` 事件并等 `threading.Event`，界面按 y/n/a 回答 | 审批发生在 worker 线程里，不能阻塞界面线程 |
| 审批「always」 | 写用户级规则文件 | 同左（`ToolExecutor._remember`） | M1 已有 |
| MCP 传输 | stdio 优先，SSE/HTTP 预留 | 只实现 stdio；`url`/`headers` 在配置里但未使用 | mcp SDK 2.x 的 http 传输 API 与设计稿写的不一致 |
| MCP 生命周期 | Session 创建时连接、销毁时断开 | 连接在 `build_loop` 里建立，**不随会话结束断开** | 断开要处理一堆在途请求；MCP server 的线程会一直在（见 M5 的风险表） |
| MCP 并发 | 异步客户端 | 每个 server 一个线程 + 自己的 event loop，调用走 `run_coroutine_threadsafe` | MCP SDK 是异步的，agent 是同步的 |
| MCP 工具命名 | `mcp__<server>__<tool>` | 同左；工具另外记住 server 里的原名 | server 只认自己的名字，改了名就调不通 |
| MCP 断线重连 | 重连一次 | 同左：调用抛错时重启连接再试一次 | 失败两次就返回错误，不无限重试 |
| Hooks 顺序 | PreToolUse 在权限检查之前 | 同左：先跑 hook（可改参数），再判权限 | 被审批的必须是改写后的命令 |
| Stop hook | 要求 agent 继续 | 同左，但一轮最多拦 3 次 | 拦不住就停，避免死循环烧钱 |
| Hook 失败 | 记日志不阻断（可选 strict） | 同左；超时按「放行」处理 | 同上 |
| 内置命令 | 17 个 | M3 交付时 19 个（多了 `/status` `/export` `/context`），今天 25 个 | M0/M1/M2 已有的能力顺手接进来，后面的里程碑继续加 |
| 自定义命令 | front matter + `$ARGUMENTS`/`$1` | 同左；`argument-hint` 也接受 YAML 列表 | `argument-hint: [file]` 在 YAML 里是列表 |
| 工具限制 | 临时构造受限 Registry | 同左；命令结束后原样换回 | 命令跑在自己的上下文里 |
| 配置 | `MCPConfig` / `HookConfig` / `UIConfig` | 同左；`ui.theme` 暂未使用 | 主题跟随终端，没有单独的开关 |
| 文档 | `docs/usage/` | `docs/usage/coderagent_{commands,mcp,hooks}.md` | 现有 `docs/usage/` 是 `mini` 的文档，单独开一组 |

**实测**（DeepSeek，`deepseek/deepseek-flash`）：

- TUI 真机（pty）跑通：状态栏显示 `deepseek/deepseek-flash | 1.5k/64k | $0.0000 | <cwd> | default`，模型调用 `ls` 后工具卡片与流式回答都正常显示。
- 真实 MCP server（本地 20 行的 echo server）通过 stdio 连接，`mcp__echo__echo` 可调用；server 进程自杀后客户端自动重连一次并调用成功。
- 自定义命令 `/commit README.md` 真实跑通，工具被限制为 `bash` + `read`。
