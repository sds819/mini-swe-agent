# M5 — Web 版

> 目标：把 coding agent 从「终端里的一个程序」搬到浏览器里，并让模型参数可以在网页上配。
> 依赖：M0–M4 全部完成。本里程碑**不改核心架构**，只加一层新的交互面。
> 状态：已完成。代码已落地，测试与使用文档已补齐。
> 配套：[M5-web-modules.md](M5-web-modules.md) 讲模块与函数级别的设计（本文讲总体设计）。

---

## 1. 功能范围

| 编号 | 功能 | 优先级 | 说明 |
|---|---|---|---|
| F5.1 | 模型配置页 | P0 | `/settings`，显式字段 + 自由 kwargs，含分层来源预览与连通性测试 |
| F5.2 | 聊天页 | P0 | `/`，跑 agent、流式输出、工具卡、diff 预览 |
| F5.3 | 事件流 | P0 | SSE 推送；环形缓冲 + `since` 断线续传 |
| F5.4 | 工具审批 | P0 | 浏览器点 Allow / Deny / Always；超时自动 DENY |
| F5.5 | 会话管理 | P1 | 列表 / 续接 / fork / 回放 |
| F5.6 | 文件浏览与 diff | P1 | 目录树、读文件、工作区 diff |
| F5.7 | Slash 命令 | P1 | 复用 `ui/commands` 的 23 个内置命令与自定义命令 |
| F5.8 | 中断 | P1 | `/interrupt` 停掉正在跑的一轮 |

---

## 2. 总体分层与边界

### 2.1 为什么不用改核心

web 版需要的四件事，核心里**已经有了**，所以本里程碑一行核心逻辑都不重写：

| 需要的能力 | 现成的地基 |
|---|---|
| 模型参数可结构化读写 | pydantic `ModelConfig`（`config/schema.py:38`），`model_kwargs` 直传 `litellm.completion` |
| 配置分层 | `config/loader.py` 的四层合并（defaults < 项目 < 用户 < CLI） |
| 事件可订阅 | `core/events.py:61` 的 `EventBus`，同步发布/订阅，TUI 已是它的一个订阅者 |
| 回合可放到别的线程 | 核心全程同步，`ui/tui.py:267` 已经在工作线程里跑 turn |

所以 web 版 = **一个 FastAPI 应用 + 每会话一个工作线程 + SSE 把事件推给浏览器**，
外加复用现有的工具、diff、checkpoint、slash 命令。

### 2.2 模块布局

```
src/coderagent/web/
├── __init__.py      # 只有 docstring。绝不在这里 import fastapi
├── app.py           # create_app(config, cwd, ...) -> FastAPI
├── api.py           # APIRouter(prefix="/api")：全部 REST + SSE 端点
├── sessions.py      # SessionRegistry + SessionRuntime：线程、环形缓冲、turn 执行
├── events.py        # normalize(Event) -> list[item]：核心事件 → 前端条目
├── approver.py      # WebApprover：阻塞式审批，答案由 HTTP 送回
├── config_api.py    # 读写 ~/.coderagent/config.yaml、分层预览、脱敏、连通性测试
├── files.py         # 文件浏览：越界检查、列目录、读文件、diff
├── server.py        # serve(cwd, host, port)：uvicorn 入口
├── templates/       # base.html / chat.html / settings.html（Jinja2）
└── static/          # app.css / app.js（原生 JS，无构建步骤）
```

`web/__init__.py` 只放 docstring：`from coderagent.web.server import serve` 在
`ui/cli.py` 的 `web` 子命令里**惰性导入**（照抄 `coder export` 的写法，`ui/cli.py:141`）。
这样 fastapi 永远不是硬依赖——没装 `web` extra 的人 import `coderagent` 不受影响。

---

## 3. 会话运行时

### 3.1 线程模型

```
turn 线程                          事件循环
──────────                         ─────────
loop.run_turn()                   SSE 生成器 await queue.get()
  bus.publish(Event) ──► 订阅者（turn 线程）
                            │
                            ▼
                     normalize(event) → item
                            ▼
                     runtime.emit(item)
                       ├─ 环形缓冲 deque(maxlen=1000) 追加 {"seq":n, ...}
                       │    （瞬时条目例外：流式的增量只推给订阅者，不留）
                       └─ 每个订阅者：loop.call_soon_threadsafe(queue.put_nowait, item)
```

- **每会话一个 worker 线程**，`queue.Queue` 收活；turn 期间持 `busy` 标志。
- **FastAPI 事件循环里绝不跑 agent 代码**：碰文件系统/模型/loop 的端点都写成普通 `def`
  （Starlette 丢线程池），或直接交给会话 worker。
- `build_loop`（`run.py:90`）**每会话建一次并缓存**：它会起 MCP server 线程（`run.py:111`）
  且会往全局命令表追加（`run.py:117`），不能每请求建。
- 事件订阅要**逐个 EventType 注册**（`EventBus` 没有通配订阅，`core/events.py:67`）：
  `for t in EventType: bus.subscribe(t, handler)`。
- `loop.cancel = runtime.cancel.is_set`，每轮前赋值（照 `ui/tui.py:273`）。

### 3.2 缓冲与回放

`SessionRuntime._replay()` 在构造时把事件日志过一遍 `normalize()` 灌进环形缓冲。
于是 `/items?since=0` 与 SSE 流**共用一个 `seq` 空间**：

- 浏览器打开页面 → 拉 `/items?since=0`（拿到历史）→ 打开 `/stream?since=<seq>`（拿增量）。
- 断线重连 → 带 `since=<seq>` → `attach()` 把缓冲里 `seq > since` 的塞进队列。
- **流式的增量（`text_delta` / `reasoning_delta`）是瞬时的**：它们有 `seq`（顺序不变），
  但**不进缓冲**。晚到的浏览器看不到它们，但能看到随后那条完整的 `assistant_message`。

### 3.3 一个会话一次只有一个 turn

`SessionStore.append` 本身没有锁（`core/session.py:75`），所以并发写会串。
`SessionRuntime.submit()` 在 `busy` 已置位时抛 `SessionBusy` → `/messages` 返回 **409**。

### 3.4 会话换 id 的问题

`/clear`、`/resume` 会换 session id（`ui/commands/builtin.py:89`、`:99` 调 `loop.switch_to`）。
浏览器还在往旧 id 推流，所以 `SessionRegistry` 必须 **re-key**：

```python
def rekey(self, runtime, old_id, new_id):
    self._runtimes.pop(old_id, None)
    self._runtimes[new_id] = runtime
```

运行时同时发一条 `session_switched` 条目，前端据此换订阅目标。

---

## 4. 事件到条目的翻译

核心说的是事件，浏览器说的是条目。`web/events.py` 的 `normalize(event) -> list[dict]`
是唯一的翻译层。

| 核心事件 | 条目 kind | 备注 |
|---|---|---|
| `USER_MESSAGE` | `user_message` | |
| `ASSISTANT_MESSAGE` | `assistant_message` | `reasoning` 可折叠，受 `config.ui.show_reasoning` 控制 |
| `TEXT_DELTA` | `text_delta` | **不入日志**，只在事件总线上（`core/events.py:16`）；也**不进环形缓冲**（瞬时，见 §17.1） |
| `REASONING` | `reasoning_delta` | 同上 |
| `TOOL_CALL` | `tool_call` | 一条动作一个条目；标题用 `ui/widgets/tool_card.py:11` 的 `summarize(args)` |
| `TOOL_RESULT` | `tool_result` | **两种 payload，见下** |
| `APPROVAL_REQUEST` | `approval_request` | 带 `id`/`tool`/`params`/`reason` |
| `APPROVAL_RESPONSE` | `approval_response` | 带 `timed_out` |
| `STATE_CHANGE` | `state` | |
| `COMPACTION` / `REFLECTION` / `REVERTED` | `compaction` / `reflection` / `reverted` | 分隔线 |
| `ERROR` | `error` | 红条 |

### 4.1 `TOOL_RESULT` 的两种形状

| 来源 | payload | 含义 |
|---|---|---|
| 执行器（`tools/executor.py:167`） | `{"tool": ..., "tool_call_id": ..., "content": ..., "diff": ...}` | 知道是哪个工具、还带 diff |
| 上下文（`core/context.py:110`） | `{"messages": [ ... ]}` | 记录模型**实际看到**的观察值 |

`normalize()` 必须区分：`"tool" in payload` 才是执行器那一版。前端按 `tool_call_id`
更新同一张卡，不重复渲染。

### 4.2 diff 的持久化

执行器那一版原本**只发不存**，回放就看不到 diff。改 `tools/executor.py` 让它也
`store.append` 进事件日志：

```python
ctx.bus.publish(event)
if self.store is not None:
    """The log keeps the result, so that the replay shows the diff of the change."""
    self.store.append(ctx.session.id, event)
```

副作用：事件日志里 `TOOL_RESULT` 出现两次（执行器一次、上下文一次）。
`core/context.py:76` 的 `restore()` 不受影响（它读 `payload["messages"]`，执行器变体没这个键）。
`tests/coderagent/test_loop.py` 的事件序列断言要跟着改。

---

## 5. 传输：SSE + REST

| 方向 | 机制 | 为什么 |
|---|---|---|
| 服务端 → 浏览器 | **SSE**（`text/event-stream`） | 单向推送、自带重连、不需要额外协议 |
| 浏览器 → 服务端 | **REST**（JSON） | 审批/命令/配置都是「一次请求一次回答」 |

**不用 WebSocket**：没有双向的实时需求，SSE 的重连与心跳是现成的。

SSE 帧格式：`data: {json}\n\n`，每 15 秒一个 `: keep-alive\n\n`。
一轮结束时发 `turn_end`，流随之关闭；浏览器拿新的 `since` 重开。

---

## 6. 审批

```
agent 线程                          浏览器
──────────                          ───────
executor._prepare()
  policy.evaluate → "ask"
  approver.request(tool, params, reason)
    bus.publish(APPROVAL_REQUEST) ──► SSE ──► 渲染审批卡
    event.wait(timeout)  ⏸               │
                                         │ 用户点 Allow/Deny/Always
    event.set()  ⏵ ◄── POST /api/approvals/{id} ──┘
  继续执行 / 拒绝
```

- `WebApprover`（`web/approver.py`）在 worker 线程上阻塞，`threading.Event` 唤醒。
- **超时自动 DENY**（与 `ui/tui.py:58` 一致），默认 300 秒，超时再发一条
  `approval_response{timed_out:true}` 让前端解释原因。
- 未知/过期 id → **404**。
- **Always allow** 会往用户规则文件 `~/.coderagent/rules.yaml` 写一条规则
  （`tools/executor.py:126` → `tools/rules.py:103` `add_rule`）。UI 必须明确提示这一点。
- Deny → 模型收到「用户拒绝」（`tools/executor.py:122`），模型会改口而不是硬改。

---

## 7. Slash 命令

原样复用 `ui/commands/__init__.py:80` 的 `run(context, line)`——23 个内置命令和自定义命令
都只通过 `context.say(...)` 说话，零 textual 依赖。

- `CommandContext.output` 接到 `runtime.emit({"kind": "command_output", "text": ...})`。
- **命令在会话 worker 线程里跑**（`/compact` 会触发一次模型调用，`/rewind` 碰文件系统）。
- 命令换 session id 时，registry 重新 key（见 §3.4）。

### 7.1 `register()` 必须去重

`ui/commands/__init__.py:54` 的 `register()` 原本无条件 append。web 是**每会话一个 loop**，
每建一次 loop 就注册一遍项目自定义命令 → 全局命令表无限膨胀、`/help` 出现重复。
改成按名字去重（同名替换）。

---

## 8. 模型配置页

### 8.1 显式字段

| 字段 | 落点 | 说明 |
|---|---|---|
| `model_name` | `model.model_name` | 如 `deepseek/deepseek-flash` |
| `api_base` | `model.model_kwargs.api_base` | **显式字段**，因为它直通 litellm |
| `api_key` | `model.model_kwargs.api_key` | 密码框；服务端只回 `api_key_set` + 掩码 hint |
| `max_retries` | `model.max_retries` | 死配置，接线见 §8.4 |
| `set_cache_control` | `model.set_cache_control` | `ephemeral` / 空 |
| `routing` | `model.routing` | `{purpose: model}` |
| `routing_rules` | `model.routing_rules` | `{when, purpose}` 行 |
| 附加 kwargs | `model.model_kwargs` 其余 | 自由 YAML/JSON 编辑框 |

### 8.2 分层预览

`GET /api/config` 返回 `sources: {"model_name": "user", "api_base": "project", ...}`，
按优先级 defaults < project < user < env 逐层找第一个定义该 key 的层。

### 8.3 写入

只写 `config_home()/"config.yaml"`（`paths.py:7`），**项目级 `.coderagent/config.yaml` 永不写**
（它会进 git）。读现有 YAML → 只改 `model:` 下用户提交的子键 → `yaml.safe_dump(sort_keys=False)`
写回。未知顶层段（`agent:`/`tools:`/`mcp:`…）与未知 `model:` 子键原样保留。

**已知代价**：注释会丢（不引 ruamel）。

**api_key 语义**：省略/`null` → 保留原值；非空字符串 → 替换；`""` → 删除。

**改完不热更新**：运行中的 server 保留启动时的 `Config`；**新会话**建 loop 时重新
`load_config()` 生效（`web/sessions.py` 的 `SessionRegistry.create()`）。页面要提示
「新配置对新会话生效，当前会话用 `/model <name>` 切换」。

### 8.4 `max_retries` 的接线

mini 的 retry 次数来自 `$MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT`
（`minisweagent/models/utils/retry.py:21`），不是 `model.max_retries`。
在 `web/server.py` 建模型前把这个环境变量设成 `model.max_retries`，一行解决；
否则表单里就是个摆设。

### 8.5 权限设置

权限分两层，作用不同：

| 层 | 改什么 | 生效时机 |
|---|---|---|
| 设置页 | 用户级配置文件的 `permissions:` 段 | **新会话** |
| 聊天页检查器 | 当前会话的 `PermissionPolicy` | **立刻** |

**写**：`web/config_api.py` 的 `write_user_permissions()`，和 `write_user_model()` 同构——
只写用户级文件，只改 `permissions.mode` / `deny_paths` / `include_dirs`，
**`permissions.rules` 原样保留**（规则是审批卡片上 `Always allow` 按钮写的，不是页面的事）。

**读**：`permissions_view(cwd, server_mode=...)` 给出 mode / modes / deny_paths /
include_dirs / source / server_mode。`source` 按 `config_layers()` 逐层判断每个字段来自哪一层，
和 §8.2 的 `sources()` 同一套办法。

**运行中切换**：`SessionRuntime.set_mode()` 原地改 `loop.executor.policy.mode` 和
`loop.session.permission_mode`——**和 `/mode` 命令完全相同的两行**。策略是执行器问的那个对象，
所以下一个工具调用就能看到；`ContextEngine` 拿的是同一个策略对象，`<permission_mode>`
提示会自动跟着变，不用重建上下文。loop 还没建时只记下模式，`build_loop()` 用它。

**`--permission-mode` 盖过文件**：`build_policy()` 是 `permission_mode or config.permissions.mode`
（`run.py:68`）。服务器带模式启动时，配置文件里的 `permissions.mode` 是死的——页面要**如实说**，
不能让用户以为改了生效了（`server_mode` 非空时 `source["mode"]` 报 `server`）。

**一个坑**：`status()` 在 loop 还没建时返回的是 `config.permissions.mode`，不是会话自己的模式。
不改这一行，新建会话切换后状态栏显示旧值。

**不做的**：浏览器里编辑 `rules.yaml`；把权限写进项目级 `.coderagent/config.yaml`（会进 git）。

---

## 9. 文件浏览与 diff

| 功能 | 复用 |
|---|---|
| 列目录 | `tools/builtin/search.py` 的 `LsTool`（遍历逻辑抽成公开的 `list_entries(target, depth)`） |
| 读文件 | `tools/builtin/fs.py` 的 `ReadTool`（自带行号与截断） |
| 搜索 | `GlobTool`/`GrepTool`（纯 Python，不依赖 rg） |
| 写操作预览 diff | `ui/widgets/diff_view.py:31` `prospective_diff(tool, params, cwd)` |
| 统一 diff 渲染 | `ui/widgets/diff_view.py:9` `make_diff` |
| 工作区 diff | `git diff -- <path>`（同 `ui/commands/builtin.py:139`） |

### 9.1 路径安全三层

```
Path.resolve()  →  边界检查（必须在 cwd 或 permissions.include_dirs 里）  →  工具自身的 resolve_path
```

越界 → **403**，文案沿用 `tools/permissions.py:117` 的写法。

> **不能用 `policy.evaluate("read", ...)` 当边界检查**——`tools/permissions.py:114-116`
> 允许 `allow` 规则覆盖边界检查，那会让规则文件把整块磁盘暴露给浏览器。
> **必须直接用边界检查**。

所以 `tools/permissions.py` 的 `_within_bounds` 提成公开的 `within_bounds(path) -> bool`，
web 直接复用，不重写路径安全逻辑。

---

## 10. 前端

- **服务端不出 HTML**，只发 JSON 条目；Jinja 模板只渲染外壳。
  这样逻辑不依赖浏览器就能测。
- 三个页面：`/`（聊天）、`/settings`（模型配置）、`GET /static/*`。
- 左栏会话列表 + 文件树，中栏对话 + 输入框，顶栏状态条。
- 原生 JS，无构建步骤（`static/app.js` ~500 行）。
- **页面不整体滚动**：每栏自己滚；对话区只滚自己的 `scrollTop`，跟着新内容走，
  除非用户往上翻。历史对话折成一个可展开的块（见 [M5-web-modules §11.4](M5-web-modules.md)）。

| 条目 kind | 渲染 |
|---|---|
| `user_message` | 气泡 |
| `assistant_message` | 气泡（`reasoning` 可折叠） |
| `text_delta` | 追加到当前气泡（实时流式） |
| `tool_call` | 工具卡（标题用 `summarize(args)`） |
| `tool_result` | 更新同一张卡（按 `tool_call_id`），显示输出/报错/diff |
| `todos` | 待办面板 |
| `approval_request` | 审批卡（Allow / Deny / Always） |
| `command_output` | 命令输出块 |
| `state` / `error` / `compaction` | 状态条 / 红条 / 分隔线 |

---

## 11. 安全模型

| 关注点 | 处理 |
|---|---|
| 暴露面 | 默认 `127.0.0.1`；`--host` 非回环时打印警告；uvicorn 单 worker |
| 无认证 | **明确风险**：能访问端口的人就能驱动 agent 在 `cwd` 内跑 shell。本机单用户工具，信任模型同 `coder` 命令行。写进文档和 CLI help，不藏着 |
| 浏览器 CSRF | 所有写接口要求 `X-Coder-Client: 1` 头 → 触发预检，而 CORS 未开 → 浏览器跨站发不了；curl 不受影响 |
| 路径穿越 | `resolve()` + 边界检查，越界 403 |
| 密钥 | api_key 只写用户级文件；API 只回 `api_key_set` + 掩码；分层预览里所有含 `key`/`token`/`secret` 的项都被抹掉 |
| 日志污染 | `web/server.py` 里设 `litellm.suppress_debug_info = True`（同 `ui/cli.py:16`），否则 litellm 的 banner 会打乱 SSE |

---

## 12. 对既有文件的改动（全部是加法）

| 文件 | 改动 |
|---|---|
| `tools/executor.py` | `_publish` 里把带 diff 的 `TOOL_RESULT` 也写进事件日志 |
| `tools/permissions.py` | `_within_bounds` → 公开的 `within_bounds` |
| `tools/builtin/search.py` | `LsTool.run` 的遍历逻辑抽成公开 `list_entries`（行为不变） |
| `ui/commands/__init__.py` | `register()` 按名字去重 |
| `ui/cli.py` | 新增 `web` 子命令（函数内惰性导入）；根回调的提前 `return` 不变 |
| `config/loader.py` | 抽出 `config_layers(cwd)`，`load_config` 复用它 |
| `run.py` / `testing/factory.py` | 把 `store` 传给 `ToolExecutor` |
| `pyproject.toml` | `web` extra + `dev` extra 加 fastapi/uvicorn；package-data 加模板与静态文件 |

---

## 13. 任务分解

### T5.1 依赖
- [x] `pyproject.toml` 的 `web` extra + package-data
- [x] 本地装上 fastapi/uvicorn

### T5.2 web 核心
- [x] `web/events.py`（事件 → 条目）
- [x] `web/sessions.py`（runtime + registry）
- [x] `web/approver.py`（阻塞式审批）
- [x] 既有文件的 2/3/4 项改动（permissions / search / register 去重）

### T5.3 API
- [x] `web/api.py` + `web/app.py` + `web/server.py`
- [x] `coder web` 子命令
- [x] 会话、消息、items、stream、status、metrics、changes、resume、fork、interrupt、approvals

### T5.4 文件与配置
- [x] `web/files.py` + 文件/diff 端点
- [x] `web/config_api.py` + 配置端点（脱敏、分层、写回、连通性测试）

### T5.5 前端
- [x] templates + static + 两个页面

### T5.6 diff 持久化
- [x] `tools/executor.py` 持久化带 diff 的 `TOOL_RESULT`
- [x] 同步改 `tests/coderagent/test_loop.py` 的断言

### T5.7 测试
- [x] `tests/coderagent/web/conftest.py`
- [x] `test_api_sessions.py`
- [x] `test_api_chat.py`
- [x] `test_stream.py`
- [x] `test_approvals.py`
- [x] `test_api_config.py`
- [x] `test_files.py`
- [x] `test_commands.py`
- [x] `test_interrupt.py`

### T5.8 文档
- [x] `docs/usage/coderagent_web.md`
- [x] `docs/usage/coderagent.md` 与 `coderagent_quickstart.md` 加链接
- [x] `mkdocs.yml` nav 加条目

### T5.9 实跑
- [x] 用真实模型跑一遍，把踩到的坑回写进文档

### T5.10 权限设置
- [x] `config_api.permissions_view()` / `write_user_permissions()`（读写用户级 `permissions:` 段）
- [x] `SessionRuntime.set_mode()`（运行中切换）+ `status()` 的模式
- [x] `PUT /api/config/permissions` 与 `POST /api/sessions/{id}/mode`（非法模式 400）
- [x] 设置页的权限表单 + 聊天页检查器的模式下拉框
- [x] `tests/coderagent/web/test_api_permissions.py`

---

## 14. 测试计划

`tests/coderagent/web/`，pytest，**不用 mock**。`fastapi` 当前环境没装 → 测试文件首行
`pytest.importorskip("fastapi")`；同时把 fastapi/uvicorn 加进 `dev` extra。

fixture 用 `load_config([], cwd=tmp_path)` + `ScriptedModel` 建 app，`TestClient(app)` 出 client。
`MSWEA_CODER_HOME` 已被 `tests/coderagent/conftest.py:6` 的 autouse fixture 指向 tmp → 隔离。
**所有 web 代码必须在调用时读 `config_home()`，不能 import 时缓存**。

| 文件 | 断言要点 |
|---|---|
| `test_api_sessions.py` | 建会话 201；列表含它；fork 出新 id 且原日志未变；`/events` 回放条目类型正确；`/metrics` 的 total 与 `collect(events)` 一致；turn 跑着时再 `/messages` → **409** |
| `test_api_chat.py` | 脚本模型先发一个 `bash` 工具调用再收尾；`/messages` → 202；轮询 `/items` 直到 `turn_end`；条目类型含 `user_message`/`tool_call`/`tool_result`/`assistant_message`/`turn_end`；工具输出内容正确；`turn_end.cost` 等于脚本里的费用 |
| `test_stream.py` | `client.stream(...)` 产出的 `data:` 行 JSON 有 `seq`/`kind`，最后一条是 `turn_end`。（流迭代期间别发别的请求，会死锁——所以才需要 `/items` 轮询端点） |
| `test_approvals.py` | 出现 `approval_request` → `POST /api/approvals/{id}` allow → 工具真的执行 → 后续 `tool_result`；不回答 → 工具结果是拒绝信息；未知 id → 404；`ui.approval_timeout=1` 时约 1s 后自动 DENY |
| `test_api_config.py` | `PUT /api/config/model` 写的是 `~/.coderagent/config.yaml`，**不是** `<cwd>/.coderagent/config.yaml`；原有的 `agent:` 段没被冲掉；`GET /api/config` 里 api_key 不明文且 `api_key_set` 为 true；写之前 `sources.model_name=="defaults"`、写之后 `=="user"`；`POST /api/config/model/test` 对坏模型返回 `{"ok":false,...}` 而不是抛异常 |
| `test_files.py` | 列目录、读文件正常；`../../etc/passwd` 与绝对路径 → **403**；`/api/diff` 返回 diff 或错误，绝不 500 |
| `test_commands.py` | `{"text":"/help"}` → 出现 `command_output`；`/api/commands` 含 `help`/`model`/`mode`/`resume`/`fork`；`/clear` 后 session id 变了且 registry 已 re-key（新 id 可流） |
| `test_interrupt.py` | 脚本模型一直调工具 → `POST /interrupt` → turn 以 `stop_reason=="interrupted"` 结束 |

风格遵守 AGENTS.md：pytest、单行 `assert func() == b`、parametrize 第一个参数是 tuple
第二个是 list、`ScriptedModel` 是仓库内的真 fake 而非 mock。

---

## 15. 风险

| 风险 | 对策 |
|---|---|
| 无认证的可执行 shell 的服务（高） | 只听本机 + 防 CSRF 头 + 文档写明；不做 token |
| 每会话一个 loop ⇒ 每会话一套 MCP server 线程（中） | loop 懒建（用到才建），文档说明 |
| `register()` 去重是对全局命令表的改动（低） | 只影响同名命令的重复注册，行为等价 |
| 改 `tools/executor.py` 持久化 `TOOL_RESULT` 会改变事件日志体积与一处既有断言（低） | 单独一个提交，方便回滚 |
| `model.max_retries` 是死配置（低） | 用环境变量接线，一行 |
| `TEXT_DELTA`/`REASONING` 不入日志（设计如此） | 回放只有最终消息，文档说明 |

---

## 16. Definition of Done

- [x] 浏览器里能完整跑一轮：发消息 → 看流式输出 → 触发审批 → 允许 → 看工具卡与 diff
      （走 HTTP API 与事件流验证；审批与工具卡另有测试覆盖）
- [x] `/settings` 能改 model_name / api_base / api_key 并测试连通性，写进用户级配置
- [x] 权限能改：设置页写用户级 `permissions:` 段（新会话生效），聊天页能切换运行中会话的模式（立刻生效）
- [x] 文件树能浏览、读文件、看 diff，越界路径返回 403
- [x] 会话能列表 / 续接 / fork，回放能看到历史消息与工具 diff
- [x] `pytest tests/coderagent -q` 全绿
- [x] `mkdocs build --strict` 无警告
- [x] `docs/usage/coderagent_web.md` 写完，安全模型一节明写

---

## 17. 实现说明（与原设计的偏差）

- **没有用 `X-Coder-Client` 做浏览器的写请求鉴权之外的东西**。所有写接口（消息、审批、
  中断、配置写入、配置测试）都要这个头，读接口不要。这样 `curl` 照常能用，
  跨站浏览器发不了。
- **SSE 的结束条件**：一轮结束时发 `turn_end`（命令是 `command_end`），流随之关闭，
  浏览器拿新的 `since` 重开。不用「空闲多久就关」的启发式——那会让「一轮里长时间没输出」
  的情况提前断流。**结束条件不再看 `busy`**：`turn_end` 是在 `busy` 清掉之前发的，
  用 `busy` 当条件会有竞态，流可能永远不关。
- **命令也发 `command_end`**：命令跑完发一条 `{"kind": "command_end"}`，前端与后端同一套
  「这一轮结束了」的信号。
- **每会话的 loop 懒建**（第一次跑 turn 时才 `build_loop`），避免光看一眼会话列表就起一整套
  MCP 线程。
- **命令的输出走 `command_output` 条目**，不混进对话气泡——命令不是模型说的话。

### 17.1 实跑记录（DeepSeek，2026-11-08）

真跑了一轮（`coder web --cwd /tmp/webtest --port 8799`），把踩到的写在这里：

- **`text_delta` 是逐 token 的**，一轮「say hi」就有 14 条 `text_delta`。前端按 `seq`
  追加到当前气泡是对的，但**缓冲区会被 token 吃满**：1000 条的环形缓冲，一轮长回答就
  够把前面的历史挤掉。→ **已修（Q7）**：流式的增量是**瞬时条目**，只推给正在听的浏览器，
  **不进环形缓冲**（`web/events.py` 的 `TRANSIENT_KINDS`）；整段答案随后以一条
  `assistant_message` 进缓冲。
- **环境的 API key 现在也在设置页里**：早期版本只读配置文件，所以 `DEEPSEEK_API_KEY` 这类
  环境变量在页面上看不到（`api_key_set` 是 `false`），而 agent 其实在用它。**已修**：key 的来源
  顺序是「配置 > 别名文件 > 厂商的环境变量」，`sources.api_key` 会报出它来自哪一层。
- **`sources.model_name` 显示 `env`**：`MSWEA_MODEL_NAME` 在环境里时，模型名来自环境而不是
  文件。这与 loader 的口径一致（文件 > 环境 > 默认）。
- **每轮结束有一条 `reflection` 分隔线**：那是 `settle()` 沉淀记忆的那次调用，它的钱算进
  `session_cost`（实测一轮 0.00032，会话总额 0.00050）。
- **`/help` 的输出很长**，一条 `command_output` 里塞了 25 行命令。前端要能折叠长输出。

> **待办（Q7）**：~~`text_delta` 逐 token 进缓冲，长回答会把历史挤出缓冲。~~
> **已修**：瞬时条目（`text_delta` / `reasoning_delta`）不进环形缓冲，只推给正在听的浏览器；
> 整段答案以 `assistant_message` 进缓冲。前端收到 `assistant_message` 时**替换**流式气泡
> 的内容，而不是再画一个气泡（原来会重复显示两遍）。
