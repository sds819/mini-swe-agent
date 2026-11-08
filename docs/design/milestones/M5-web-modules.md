# M5 附：Web 版模块与函数设计

> 目标：把 [M5-web-interface.md](M5-web-interface.md) 里的**总体设计**落到**模块与函数**一级：
> 每个模块负责什么、对外暴露哪些函数与签名、每个接口出入参长什么样、失败时怎么办。
> 状态：与代码同步（M5 的代码已落地，本文按现有实现逐模块描述，并标注需要补的地方）。

M5 那篇讲的是「为什么这么做」。本文讲的是「具体是哪个函数、参数是什么、返回什么」。
两者配合看：**先读 M5 的 §2–§11 建立认知，再查本文的表格定位到具体函数。**

---

## 1. 模块总览

| 模块 | 文件 | 职责 | 对外主要符号 | 依赖 |
|---|---|---|---|---|
| 包入口 | `web/__init__.py` | 只有 docstring | — | 无 |
| 事件翻译 | `web/events.py` | 核心事件 → 前端条目 | `normalize(event)` | `core.events`、`ui.widgets.tool_card` |
| 会话运行时 | `web/sessions.py` | 线程、环形缓冲、turn 执行、会话注册表 | `SessionRuntime`、`SessionRegistry`、`SessionBusy` | `core.*`、`run.build_loop/settle`、`web.approver`、`web.events` |
| 审批 | `web/approver.py` | 阻塞式审批，答案由 HTTP 送回 | `WebApprover` | `core.events`、`tools.permissions` |
| HTTP API | `web/api.py` | 全部 REST + SSE 端点 | `router`、`require_client` | FastAPI、`web.*`、`core.telemetry`、`ui.commands` |
| 应用装配 | `web/app.py` | 组装 app、挂静态资源与模板 | `create_app(...)` | `web.api`、`web.sessions` |
| 服务入口 | `web/server.py` | uvicorn 启动 | `serve(...)` | `web.app`、litellm |
| 配置 API | `web/config_api.py` | 配置分层、脱敏、写回、连通性测试 | `model_view`、`sources`、`layers_preview`、`write_user_model`、`effective_model`、`test_connection` | `config.loader`、`paths` |
| 文件浏览 | `web/files.py` | 越界检查、列目录、读文件、diff | `policy_for`、`resolve`、`directory`、`read`、`diff`、`OutsideBounds` | `tools.*` |
| 前端 | `web/static/app.js` + `templates/*.html` | 三个页面的渲染与交互 | `render(item)` 等 | 纯 REST/SSE |

**依赖方向是单向的**：`api → sessions → {approver, events}`，`app → api`，`server → app`。
`events.py` 不依赖 `sessions.py`，`sessions.py` 不依赖 `api.py` —— 这样每个模块都能单独测。

---

## 2. `web/__init__.py`

```python
"""The web interface of the coding agent."""
```

**只有一个 docstring。** 这里 `import fastapi` 会让 fastapi 变成 `coderagent` 的硬依赖，
而 fastapi 只在 `web` extra 里。`ui/cli.py` 的 `web` 子命令必须**惰性导入**：

```python
from coderagent.web.server import serve   # 写在函数体里，不在模块顶层
```

> 不变量：`import coderagent` 不会拉起 fastapi / uvicorn / jinja2。

---

## 3. `web/events.py` — 事件翻译层

### 3.1 `normalize(event: Event) -> list[dict]`

**唯一的翻译入口。** 核心说事件，浏览器说条目。一个事件可能翻译出 0 条、1 条或多条。

| `EventType` | 条目 `kind` | 额外字段 |
|---|---|---|
| `USER_MESSAGE` | `user_message` | `content` |
| `ASSISTANT_MESSAGE` | `assistant_message` | `content`、`reasoning`（取自 `message["extra"]["reasoning"]`） |
| `TEXT_DELTA` | `text_delta` | `content`（**瞬时**：不进缓冲） |
| `REASONING` | `reasoning_delta` | `content`（**瞬时**：不进缓冲） |
| `TOOL_CALL` | `tool_call` | `tool`、`args`、`summary`、`tool_call_id` |
| `TOOL_RESULT` | `tool_result`（可能多条）+ `todos` | 见 §3.2 |
| `APPROVAL_REQUEST` | `approval_request` | `id`、`tool`、`params`、`reason` |
| `APPROVAL_RESPONSE` | `approval_response` | `id`、`decision`、`timed_out` |
| `STATE_CHANGE` | `state` | payload 里所有非 `None` 的键 |
| `COMPACTION` | `compaction` | `tokens`、`cost` |
| `REFLECTION` | `reflection` | `cost`、`purpose`、`model`、`project_facts`、`user_preferences` |
| `REVERTED` | `reverted` | `messages` |
| `ERROR` | `error` | `error` |
| 其它 | — | `[]`（不渲染任何东西） |

**要点**

- `TEXT_DELTA` / `REASONING` **不入事件日志**（`core/events.py` 的设计），所以**回放没有流式过程，只有最终消息**。
- 这两种条目还是**瞬时的**（`web/events.py` 的 `TRANSIENT_KINDS`）：它们**不进环形缓冲**，
  只推给正在听的浏览器。模型逐 token 流式输出，一轮长回答能有几百条增量，进缓冲会把
  历史挤掉。整段答案随后以一条 `assistant_message` 进缓冲。
- `tool_call` 是**一条动作一个条目**：一次 `TOOL_CALL` 事件里带 `actions` 列表，多个并行工具调用
  会翻译成多条条目。`tool_call_id` 是前端把「工具卡」和「工具结果」配对的唯一依据。
- `summary` 用 `ui/widgets/tool_card.py` 的 `summarize(args)`，与 TUI 的卡片标题**同一份逻辑**，
  不在 web 层另写一套文案。

### 3.2 `_tool_result(payload: dict) -> list[dict]`

`TOOL_RESULT` 有两种 payload 形状，必须区分：

| 来源 | 判据 | 产出 |
|---|---|---|
| 执行器 `tools/executor.py` | `"tool" in payload` | 1 条，带 `tool`、`content`、`is_error`、`diff` |
| 上下文 `core/context.py` | `payload["messages"]` | 每个 message 1 条，只有 `tool_call_id`、`content`、`is_error`（`content` 以 `"Error:"` 开头即为错）、`diff=""` |

另外 `payload["todos"]` 非空时追加一条 `{"kind": "todos", "todos": [...]}`。

> 前端按 `tool_call_id` 更新同一张卡（**不新增卡片**），所以同一次调用的两条 `tool_result` 不会画两遍。
> 执行器那一条带 `diff`，上下文那一条没有 —— 前端渲染 diff 用带 diff 的那条。

---

## 4. `web/approver.py` — 阻塞式审批

```python
class WebApprover:
    def __init__(self, bus: EventBus, session_id: str = "", timeout: int = 0) -> None
    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision
    def answer(self, key: str, decision: ApprovalDecision) -> bool
```

| 函数 | 行为 | 失败 |
|---|---|---|
| `request` | 自增 id → 发 `APPROVAL_REQUEST`（payload 含 `id`/`tool`/`params`/`reason`）→ 在 `threading.Event` 上阻塞等待 | 超时（默认 300s，`timeout=0` 时用 `DEFAULT_TIMEOUT`）→ 自动 `DENY`，并补发一条 `approval_response{timed_out:true}` |
| `answer` | 记下决定 → `event.set()` → 发 `APPROVAL_RESPONSE` | id 不在等待中 → 返回 `False`（API 转 404） |

**要点**

- `session_id` 必须是**真实**会话 id（TUI 那里传的是空串），否则前端分不清是哪个会话在等。
- id 是**进程内自增整数**（`"1"`、`"2"`…），不是 uuid —— 够用且短。
- 等待表 `_events` / `_decisions` 由 `_lock` 保护；`request` 与 `answer` 可能来自不同线程
  （worker 线程 vs. 请求线程）。
- `answer` 对一个**已经超时**的 id 返回 `False` → 404。

---

## 5. `web/sessions.py` — 会话运行时与注册表

### 5.1 `SessionRuntime`

一个会话 = 一个 `EventBus` + 一个 `WebApprover` + 一个环形缓冲 + 一个工作线程。

```python
class SessionRuntime:
    def __init__(self, config, cwd, *, store=None, session=None, model=None,
                 permission_mode=None, registry=None) -> None
```

**内部状态**

| 字段 | 含义 |
|---|---|
| `bus` | 自己的事件总线，与核心的 loop 共用 |
| `approver` | 自己的审批器，`session_id` 随会话切换而更新 |
| `buffer: deque[dict]` | 环形缓冲，`maxlen=BUFFER_SIZE`（1000）；**瞬时条目不进这里** |
| `_seq` | 自增序号，**缓冲与 SSE 共用同一个 seq 空间**（瞬时条目也占号，只是不留） |
| `_subscribers: list[(loop, asyncio.Queue)]` | 正在听 SSE 的浏览器 |
| `_queue: queue.Queue[str]` | 喂给 worker 线程的任务 |
| `busy: threading.Event` | 一轮或一条命令正在跑 |
| `cancel: threading.Event` | 中断信号 |
| `_loop` | 核心的 `AgentLoop`，**懒建**（第一次跑 turn 时才建） |

**方法**

| 方法 | 契约 |
|---|---|
| `_subscribe()` | 逐个 `EventType` 注册（`EventBus` 没有通配订阅） |
| `_on_event(event)` | → `normalize` → 逐条 `emit` |
| `_replay()` | 构造时把事件日志过一遍 `normalize` 灌进缓冲，让迟到的浏览器看得到历史 |
| `emit(item) -> dict` | 分配 `seq` → 追加进缓冲（**瞬时条目除外**）→ 用 `loop.call_soon_threadsafe` 推给每个订阅者 → 返回带 `seq` 的条目 |
| `items(since: int) -> list[dict]` | 缓冲里 `seq > since` 的条目 |
| `attach(loop, subscriber, since)` | 先把漏掉的塞进队列，再登记为订阅者 |
| `detach(subscriber)` | 摘掉订阅者 |
| `submit(text) -> None` | `busy` 已置位 → 抛 `SessionBusy`；否则置位并入队 |
| `_work()` | 常驻线程：从 `_queue` 取文本 → `_execute` → 出错发 `error` 条目 → 清 `busy` |
| `_execute(text)` | 以 `/` 开头 → `_run_command`，否则 → `_run_turn` |
| `_run_turn(text)` | 跑一轮 turn，最后发 `turn_end` |
| `_run_command(line)` | 跑 slash 命令，输出走 `command_output` 条目 |
| `switch_to(session)` | 会话换了 → 更新 `approver.session_id` → 让 registry 换 key → 发 `session_switched` |
| `interrupt()` | 置 `cancel` → 发 `interrupted` 条目 |
| `resume() -> Session` | 从日志重建会话 |
| `loop() -> AgentLoop` | 懒建并缓存；建好后 `loop.cancel = self.cancel.is_set` |
| `status() -> dict` | 状态栏字段 |

**`_run_turn` 的收尾**

```python
result = loop.run_turn(text)
if result.stop_reason not in ("error", "cost_exceeded"):
    settle(loop, self.config, self.cwd)      # 每轮结束都沉淀经验
self.emit({"kind": "turn_end", "stop_reason": ..., "cost": ..., "session_cost": ..., "error": ...})
```

`settle` 放在 turn 之后、事件之前 —— 沉淀本身也是一次模型调用，它的钱由 `settle` 写进事件日志。

**`_run_command` 的输出**

```python
CommandContext(..., output=lambda text: self.emit({"kind": "command_output", "text": text}))
```

命令的输出**不混进对话气泡** —— 命令不是模型说的话。
命令跑完发一条 `{"kind": "command_end"}`，与 `turn_end` 一样是「这一轮结束了」的信号。

**`status()` 的字段**

| 字段 | 来源 |
|---|---|
| `session_id` | 当前会话（loop 已建用 loop 的，否则用自己的） |
| `model` | `loop.model.backend.model_name` |
| `tokens` / `window` | `loop.context.estimated_tokens(loop.tools)` / `context_window` |
| `cost` | `session.total_cost`（**会话的**钱，不是进程的） |
| `cwd` / `mode` / `state` / `sandbox` | 会话目录 / 权限模式 / 会话状态 / 沙箱类型 |
| `busy` | 是否正在跑 |

### 5.2 `SessionRegistry`

```python
class SessionRegistry:
    def __init__(self, config, cwd, *, store=None, model=None, permission_mode=None, config_spec=None)
    def create(self, session=None) -> SessionRuntime
    def get(self, session_id) -> SessionRuntime | None
    def runtimes(self) -> list[SessionRuntime]
    def rekey(self, runtime, old_id, new_id) -> None
    def list(self) -> list[Session]
```

| 方法 | 契约 |
|---|---|
| `create` | **重新 `load_config(self.config_spec, cwd=self.cwd)`** → 新会话用新配置（用户在设置页改的东西对新会话生效） |
| `get` | 只查内存里的 runtime |
| `rekey` | `/clear`、`/resume` 换了会话 id → 把 runtime 挪到新 key 下 |
| `list` | `store.list(cwd)`，按目录列日志里的会话 |

> 不变量：**一个会话 id 最多对应一个 runtime**。`rekey` 是唯一允许改 key 的地方。

---

## 6. `web/api.py` — HTTP 接口

`router = APIRouter(prefix="/api")`，全部挂 `/api` 下。

### 6.1 通用约定

| 约定 | 内容 |
|---|---|
| 写请求鉴权 | 必须带 `X-Coder-Client: 1`，否则 **403**。实现是 `Depends(require_client)` |
| 读请求 | 不带头也行（`curl` 方便） |
| 空消息 | `POST /messages` 文本为空 → **400** |
| 会话忙 | `POST /messages` 时 `busy` → **409** |
| 未知会话 | `GET /sessions/{id}` 找不到且日志里也没有 → **404** |
| 越界路径 | `/files`、`/file`、`/diff` → **403** |
| 阻塞端点 | 碰文件系统/模型/loop 的端点写成普通 `def`（Starlette 丢线程池），**不在事件循环里跑 agent 代码** |

### 6.2 会话

| 方法 | 路径 | 出参 | 备注 |
|---|---|---|---|
| GET | `/api/sessions?cwd=` | `{"sessions": [{id, cwd, created_at, updated_at, turns, cost, state}]}` | 默认列 `app.state.cwd` |
| POST | `/api/sessions` | `{"id", "cwd"}` | **201** |
| GET | `/api/sessions/{id}` | 同上单个 | 日志里有就重建一个 runtime |
| GET | `/api/sessions/{id}/events` | `{"items": [...]}` | **回放**：整个日志过 `normalize` |
| GET | `/api/sessions/{id}/items?since=` | `{"items": [...]}` | 环形缓冲里 `seq > since` 的，轮询友好 |
| GET | `/api/sessions/{id}/stream?since=` | SSE | 见 §6.3 |
| GET | `/api/sessions/{id}/status` | `status()` 的字段 | |
| GET | `/api/sessions/{id}/metrics` | `collect(events).to_dict()` | 与 trace / `/cost` 同一个口径 |
| GET | `/api/sessions/{id}/changes` | `{"changes": [{path, diff}]}` | checkpoint 的「之前」 vs 磁盘上的「现在」 |
| POST | `/api/sessions/{id}/resume` | `{"id"}` | 从日志重建并续接 |
| POST | `/api/sessions/{id}/fork` | `{"id", "forked_from"}` | 复制，原日志不变 |
| POST | `/api/sessions/{id}/messages` | `{"accepted", "session_id"}` | **202**；`/` 开头走命令 |
| POST | `/api/sessions/{id}/interrupt` | `{"ok": true}` | 置 cancel |

### 6.3 SSE

```
data: {"seq": 12, "kind": "assistant_message", "content": "..."}\n\n
: keep-alive\n\n          ← 每 15 秒一个（KEEP_ALIVE）
```

- 帧格式固定 `data: {json}\n\n`。
- `since=<seq>`：重连时带上，缓冲里 `seq > since` 的会先补发。
- 结束条件：`kind in ("turn_end", "command_end")` → **直接关**，不再看 `busy`
  （`turn_end` 是在 `busy` 清掉之前发的，拿 `busy` 当条件会有竞态）。
- `: keep-alive` 是注释帧，浏览器 `EventSource` 会忽略它但能保持连接。

> ⚠️ **待补**：`command_end` 现在**没人发**（见 §16 Q1）。

### 6.4 审批 / 命令

| 方法 | 路径 | 出参 | 错误 |
|---|---|---|---|
| POST | `/api/approvals/{id}` | `{"ok", "decision"}` | 决策必须是 `allow`/`deny`/`always`，否则 **400**；没人等这个 id → **404** |
| GET | `/api/commands` | `{"commands": [{name, description, aliases}]}` | 先 `load_builtins()` |

`always` 会往 `~/.coderagent/rules.yaml` 写一条规则（`tools/executor.py` → `tools/rules.py` `add_rule`）——
**前端必须提示这一点**。

### 6.5 配置

| 方法 | 路径 | 出参 |
|---|---|---|
| GET | `/api/config` | `{"model": model_view, "sources": {...}, "layers": [...], "user_config_path": str}` |
| PUT | `/api/config/model` | `{"ok", "path", "model"}` |
| POST | `/api/config/model/test` | `{"ok": true, "content", "cost", "latency_ms"}` 或 `{"ok": false, "error"}` |

### 6.6 文件

| 方法 | 路径 | 出参 | 错误 |
|---|---|---|---|
| GET | `/api/files?path=&depth=` | `{"path", "entries": [{path, name, is_dir, size}]}` | `depth` 限 `-1..10`；不是目录 → **400** |
| GET | `/api/file?path=` | `{"path", "content", "is_error"}` | 越界 → **403** |
| GET | `/api/diff?path=` | `{"path", "diff"}` | 越界 → **403**；git 失败 → 错误文本，不是 500 |

---

## 7. `web/app.py` — 应用装配

```python
def create_app(config, cwd, *, store=None, model=None, config_spec=None,
               permission_mode=None) -> FastAPI
```

**职责**：把各部分拼成一个 app。

| 步骤 | 内容 |
|---|---|
| 1 | 建 `SessionRegistry`（**不建 runtime** —— 建 app 不该起线程） |
| 2 | `app.state.registry` / `app.state.cwd` / `app.state.config` / `app.state.config_spec` |
| 3 | `app.state.config_of = lambda: load_config(spec, cwd=cwd)` —— **每次读配置都重新加载** |
| 4 | `app.include_router(router)` |
| 5 | 挂 `/static`（`StaticFiles`）与 Jinja 模板目录 |
| 6 | `GET /` → `chat.html`；`GET /settings` → `settings.html` |

> `config_of` 是给 API 用的「当前配置」入口：设置页写完文件后，`/api/config` 立刻反映新的值
> （读的是文件，不是启动时的 `app.state.config`）。

---

## 8. `web/server.py` — 服务入口

```python
def serve(cwd, host="127.0.0.1", port=8765, config_spec=None, model=None,
          permission_mode=None) -> None
```

| 步骤 | 为什么 |
|---|---|
| `import uvicorn` 放在函数体里 | uvicorn 只在 `web` extra 里 |
| `litellm.suppress_debug_info = True` | litellm 的 banner 会打乱 SSE |
| `os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = str(config.model.max_retries)` | mini 的重试次数**来自环境变量**，不是 `model.max_retries`；不接这个线，设置页的「重试次数」就是摆设 |
| `host not in LOOPBACK` → 警告 | 非回环 = 谁能访问端口谁就能驱动 agent |
| `uvicorn.run(app, host, port, log_level="warning")` | 单 worker |

---

## 9. `web/config_api.py` — 配置 API

### 9.1 常量

| 名字 | 含义 |
|---|---|
| `SECRET_MARKERS = ("key", "token", "secret", "password")` | 名字里含这些词的一律当密钥 |
| `DIRECT_FIELDS = ("model_name", "max_retries", "set_cache_control", "routing", "routing_rules")` | 直接在 `model:` 下的字段 |
| `MODEL_FIELDS = (*DIRECT_FIELDS, "api_base", "api_key")` | 配置页要展示的字段 |

### 9.2 函数

| 函数 | 出参 | 契约 |
|---|---|---|
| `is_secret(name) -> bool` | | 名字含密钥词 |
| `redact(value) -> Any` | | 递归：dict 的密钥名是密钥 → 值替换成 `"***"` |
| `hint(secret) -> str` | | `********abcd`（末 4 位）；短于 4 位 → `********` |
| `sources(cwd) -> dict[str, str]` | 字段 → 层名 | 层名：`defaults` / `project` / `user` / `env`。**文件赢过环境变量**；只有 `model_name` 会是 `env` |
| `model_view(cwd) -> dict` | 见下 | **永不含明文密钥** |
| `layers_preview(cwd) -> list[dict]` | `[{layer, model}]` | 每一层都过 `redact` |
| `user_config_path() -> Path` | | `config_home()/"config.yaml"`（`MSWEA_CODER_HOME` 生效） |
| `write_user_model(payload) -> Path` | 写后的路径 | 见 §9.3 |
| `effective_model(cwd, overrides) -> (name, kwargs)` | | 当前配置 + 表单里的覆盖 |
| `test_connection(name, kwargs) -> dict` | | 一次 `max_tokens=1` 的调用 |

**`model_view` 的字段**

```python
{"model_name", "api_base", "api_key_set": bool, "api_key_hint": str,
 "max_retries", "set_cache_control", "routing", "routing_rules",
 "model_kwargs": {...不含密钥...}}
```

### 9.3 `write_user_model(payload)` 的写回语义

| 字段 | 语义 |
|---|---|
| `model_name` | 非空字符串 → 覆盖；空/缺省 → 不动 |
| `api_base` | 非空字符串 → 写；`""` → **删**；缺省 → 不动 |
| `api_key` | 非空字符串 → 写；`""` → **删**；缺省 / `null` → **保留原值** |
| `max_retries` | 非 `None` → 写 |
| `set_cache_control` | 非 `None` → 写（空串 → `None`） |
| `routing` / `routing_rules` | 是 dict / list → 写 |
| `model_kwargs` | 逐键写入，**跳过 `api_key`/`api_base`**（这两个只能走显式字段） |

**只写用户级文件**，项目级 `.coderagent/config.yaml` 永远不动（它会进 git）。
未知顶层段（`agent:`/`tools:`/`mcp:`…）与未知的 `model:` 子键原样保留。
**已知代价：注释会丢**（`yaml.safe_dump`，不引 ruamel）。

### 9.4 `test_connection(name, kwargs)`

- 临时把 `MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT` 设成 `1`（**错的 key 要立刻失败，不是重试十次**），
  结束后恢复原值。
- 成功：`{"ok": True, "content": 前 200 字, "cost", "latency_ms"}`
- 失败：`{"ok": False, "error": "类型: 消息"}` —— **不抛异常**。

---

## 10. `web/files.py` — 文件浏览

```python
class OutsideBounds(ValueError): ...
```

| 函数 | 出参 | 契约 |
|---|---|---|
| `policy_for(config, cwd) -> PermissionPolicy` | | 权限策略**但不含规则** —— 规则能让 `allow` 越过边界检查 |
| `resolve(cwd, path, policy) -> Path` | 绝对路径 | `resolve()` 后必须 `policy.within_bounds()`；越界 → `OutsideBounds` |
| `directory(cwd, path, depth, policy) -> list[dict]` | `[{path, name, is_dir, size}]` | 用 `tools/builtin/search.py` 的 `list_entries`；不是目录 → `NotADirectoryError` |
| `read(cwd, path, policy, config) -> dict` | `{path, content, is_error}` | 用 `ReadTool`（自带行号与截断） |
| `diff(cwd, path, policy) -> str` | diff 文本 | `git diff -- <path>`；失败 → 返回错误文本，**不是异常** |

**三层路径安全**（顺序不能变）：

```
Path.resolve()  →  policy.within_bounds(path)  →  工具自己的 resolve_path
```

> **不能用 `policy.evaluate("read", ...)` 当边界检查**：`tools/permissions.py` 允许 `allow` 规则覆盖边界，
> 那等于把整块磁盘暴露给浏览器。必须用 `within_bounds`。

---

## 11. 前端 `web/static/app.js`

原生 JS，无构建步骤。全部请求都带 `X-Coder-Client: 1`。

### 11.1 状态

```javascript
state = { sessionId, seq, stream, cards, assistant, current, stick }
```

| 字段 | 用途 |
|---|---|
| `sessionId` | 当前会话；`session_switched` 之后要换 |
| `seq` | 最后看到的条目的 `seq`，重连 SSE 时用 |
| `stream` | 当前的 `EventSource` |
| `cards` | `tool_call_id` → 工具卡 DOM 节点 |
| `assistant` | 当前正在流式输出的气泡 |
| `current` | 当前这一轮的容器节点；之前的轮次折进 `#history` |
| `stick` | 对话区是否跟着新内容滚到底（用户往上翻就置 false） |

### 11.2 函数

| 函数 | 职责 |
|---|---|
| `api(path, options)` | 发请求：带客户端头、JSON 编码 body、错误抛异常 |
| `render(item)` | **唯一的渲染入口**：按 `item.kind` 分派；顺带更新 `state.seq` |
| `bubble(role, text)` / `toolCard(item)` / `fillTool(item)` / `diffView(text)` | 各种片段的 DOM 构造 |
| `target()` | 当前这一轮的容器节点（没有就建一个 `.turn`） |
| `foldTurn()` | 把上一轮折进 `#history`（`<details>`，默认收起） |
| `scrollToBottom(force)` | 对话区滚到底；`state.stick` 为 false 时不动（用户往上翻了） |
| `renderApproval(item)` | 审批卡 + Allow / Deny / Always 三个按钮 |
| `renderTodos(item)` | 待办面板（在当前这一轮里） |
| `openStream()` | 开 `EventSource('/api/sessions/{id}/stream?since={seq}')`；遇 `turn_end`/`command_end` 关闭并重开；出错 1 秒后重试 |
| `refreshStatus()` | 拉 `/status` 填顶栏与状态栏 |
| `loadChanges()` | 拉 `/changes` 渲染 diff 列表 |
| `loadSessions()` | 拉 `/sessions` 渲染左栏 |
| `openSession(id)` | 切会话：清状态 → 拉 `/items` 渲染 → 开流 |
| `listFiles(path)` / `showFile(path)` | 文件树与文件内容 |
| `loadCommands()` | 拉 `/commands` 填下拉框 |
| `parseKeyValues(text)` / `formatKeyValues(obj)` | 「附加参数」框：先试 JSON，失败按 `key: value` 行解析 |
| `startSettings()` | 设置页：填表单 → 标每字段来源 → 渲染分层预览 → 保存 / 测试连接 |

### 11.3 条目 → 渲染

| `kind` | 渲染 |
|---|---|
| `user_message` | 气泡 |
| `assistant_message` | 气泡；**若正在流式输出，则替换那个气泡的内容**（否则同一段话会显示两遍） |
| `text_delta` | 追加到当前气泡 |
| `reasoning_delta` | 折叠框 |
| `tool_call` | 工具卡（标题用 `summary`） |
| `tool_result` | **更新同一张卡**（按 `tool_call_id`），显示输出 / 报错 / diff |
| `todos` | 待办面板 |
| `approval_request` | 审批卡 |
| `command_output` | 命令输出块 |
| `state` / `error` / `compaction` / `reflection` / `reverted` | 状态条 / 红条 / 分隔线 |

### 11.4 版面：页面不滚，对话区滚，历史折起来

三条要求，各有各的做法：

| 要求 | 做法 |
|---|---|
| **页面本身不滚动** | `body` 是 `height:100vh` 的纵向 flex，`overflow:hidden`；`.layout` 是 `flex:1; min-height:0` 的 grid，三栏各自 `overflow:auto`。设置页的 `.page` 自己滚。 |
| **对话区及时滚到底** | `scrollToBottom()` 直接改 `#messages` 的 `scrollTop`（**不用 `scrollIntoView`** —— 它会把整页也滚一遍）。`#messages` 的 `scroll` 事件维护 `state.stick`：用户离底部 40px 以内才算「在底部」，否则新内容不再自动跟随。 |
| **历史对话折叠** | 一轮 = 一个 `.turn` 容器（`user_message` 开新一轮）。`foldTurn()` 把上一轮挪进 `#history`（`<details>`，默认收起，标题写着几轮）。当前这轮永远展开。 |

> 三栏的高度是 `flex` + `min-height:0` 算出来的，不写死像素；顶栏高度一变也不会错位。

---

## 12. 模板 `web/templates/`

| 文件 | 内容 | 关键 id |
|---|---|---|
| `base.html` | 外壳：顶栏 + 导航 + `{% block content %}` | `#status` |
| `chat.html` | 三栏：会话+文件 / 对话 / 状态+变更+文件 | `#sessions`、`#files`、`#messages`、`#composer`、`#input`、`#command-list`、`#run-command`、`#interrupt`、`#status-fields`、`#changes`、`#file-view` |
| `settings.html` | 模型表单 | `#model-name`、`#api-base`、`#api-key`、`#max-retries`、`#set-cache-control`、`#routing`、`#routing-rules`、`#model-kwargs`、`#layers`、`#config-path`、`#config-message`、`#test-connection`、`source-<field>` |

模板只渲染外壳，**逻辑全在 `app.js`**。

---

## 13. 不变量清单

写代码与写测试时都对着这张表检查：

| # | 不变量 |
|---|---|
| I1 | `import coderagent` 不会拉起 fastapi / uvicorn / jinja2 |
| I2 | 核心逻辑一行没改：web 只是**另一个订阅者** |
| I3 | 事件循环里**绝不**跑 agent 代码（碰文件系统 / 模型 / loop 的端点都是普通 `def`） |
| I4 | 一个会话最多一个 runtime；换 id 只能通过 `registry.rekey` |
| I5 | 一个会话同时只有一轮（第二个 `/messages` → 409） |
| I6 | `seq` 在缓冲与 SSE 里是**同一个空间** |
| I7 | api_key **永不明文出服务器**；只回 `api_key_set` + `api_key_hint` |
| I8 | 项目级配置**永不写**；只写 `config_home()/config.yaml` |
| I9 | 写接口都要 `X-Coder-Client: 1` |
| I10 | 路径越界 → **403**，且边界检查不被规则放宽 |
| I11 | 审批**没有回答就是拒绝**（超时自动 DENY），从不静默放行 |
| I12 | 会话的钱 = 事件日志里所有模型调用之和（live / metrics / trace 同一个数） |
| I13 | 流式的增量（`text_delta` / `reasoning_delta`）**不进缓冲**：整段答案以一条 `assistant_message` 进缓冲 |
| I14 | 页面**不整体滚动**：每栏自己滚；对话区只滚自己的 `scrollTop`，不动页面 |

---

## 14. 错误与状态码

| 码 | 什么时候 |
|---|---|
| 200 | 正常 |
| 201 | 建会话 |
| 202 | 收下消息（异步跑） |
| 400 | 空消息 / 非法审批决策 / 不是目录 / 读文件失败 |
| 403 | 缺 `X-Coder-Client` 头 / 路径越界 |
| 404 | 未知会话 / 无人等待的审批 id |
| 409 | 会话正忙 |
| 500 | 未预期的异常（**目标是不出现**） |

---

## 15. 扩展点

| 想加什么 | 改哪里 |
|---|---|
| 新的事件类型 | `web/events.py` 的 `normalize` 加一个分支 + `app.js` 的 `render` 加一个 case |
| 新的 API 端点 | `web/api.py` 加路由（写接口记得挂 `Depends(require_client)`） |
| 新的内置命令 | `ui/commands/builtin.py` —— web **自动就有**（`/api/commands` 与 `run()` 都是复用） |
| 新的模型设置 | `config_api.py` 的 `DIRECT_FIELDS` + `model_view` + `write_user_model` + 设置页加字段 |
| 新的页面 | `app.py` 加 `templates.TemplateResponse` + `mkdocs.yml` nav |

---

## 16. 未决问题

| # | 问题 | 影响 |
|---|---|---|
| ~~Q1~~ | ~~命令跑完没有 `command_end`~~ → **已修**：`_run_command` 末尾发 `{"kind": "command_end"}` | — |
| ~~Q2~~ | ~~`turn_end` 的关闭条件带 `not runtime.busy.is_set()`~~ → **已修**：SSE 见到 `turn_end`/`command_end` 就关，不再看 `busy` | — |
| Q3 | `changes` 端点用 checkpoint 的「之前」对比磁盘上的「现在」 | 没走 checkpoint 的写操作不会出现在变更列表里 |
| Q4 | `model_view` 的 `model_kwargs` 过滤掉了密钥，所以前端**看不到** `api_base` 之外的额外密钥 | 有意的，但要在设置页说明 |
| Q5 | 每个会话一个 `AgentLoop` → 每个会话一套 MCP server 线程 | loop 已懒建；会话多了仍会涨 |
| Q6 | **命令换了会话 id 之后，旧 id 的 `/items` 拿不到命令输出**：环形缓冲跟着 runtime 走（re-key 之后旧 id 下是一个从日志重建的新 runtime），而命令输出**不入日志** | 浏览器走 SSE 不受影响（它收到 `session_switched` 后改订新 id）；但**轮询 `/items` 的客户端会丢命令输出**。要么把命令输出写进日志，要么让 registry 在 re-key 时把旧 id 指向同一个 runtime |
| ~~Q7~~ | ~~`text_delta` 逐 token 进缓冲，长回答把历史挤出缓冲~~ → **已修**：流式增量是瞬时条目，不进缓冲；整段答案以 `assistant_message` 进缓冲 | — |
| Q8 | 前端「流式气泡被 `assistant_message` 替换」这层逻辑只在浏览器里，仓库里没有 JS 测试设施 | 已用 node 假 DOM 手验过（重复气泡消失）；将来加 JS 测试时补一条 |
