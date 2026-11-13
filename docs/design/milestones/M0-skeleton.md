# M0 — 骨架与配置

> 目标：跑通「一个可持久化、可恢复的多轮会话」，不引入工具系统、权限、压缩。
> 产出：一个 `coder` CLI，能以 headless 模式完成多轮对话并落盘 JSONL 轨迹。
> 依赖：无（首个里程碑）。
> 后续解锁：M1 工具系统、M2 上下文治理。

---

## 1. 交付物清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `src/coderagent/__init__.py` | 导出 `__version__`、公共 Protocol |
| 新增 | `src/coderagent/core/protocols.py` | `ModelBackend`、`ToolExecutor` 协议 |
| 新增 | `src/coderagent/core/events.py` | `Event`、`EventType`、`EventBus` |
| 新增 | `src/coderagent/core/session.py` | `Session`、`SessionState`、`SessionStore` |
| 新增 | `src/coderagent/core/loop.py` | `AgentLoop`（单轮 turn 执行） |
| 新增 | `src/coderagent/models/gateway.py` | `ModelGateway`（非流式雏形） |
| 新增 | `src/coderagent/config/schema.py` | pydantic 配置模型 |
| 新增 | `src/coderagent/config/defaults.yaml` | 内置默认配置 |
| 新增 | `src/coderagent/config/loader.py` | 四层配置合并 |
| 新增 | `src/coderagent/ui/cli.py` | typer 入口 |
| 新增 | `src/coderagent/ui/render.py` | text / json 输出渲染 |
| 新增 | `src/coderagent/testing/scripted_model.py` | 脚本化假模型（测试用） |
| 新增 | `src/coderagent/run.py` | 装配入口 |
| 修改 | `pyproject.toml` | packages.find、project.scripts、依赖 |
| 新增 | `tests/coderagent/test_*.py` | 单测 |

---

## 2. 关键接口

### 2.1 事件系统

```python
# src/coderagent/core/events.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TEXT_DELTA = "text_delta"        # 不写进事件日志，只在总线上
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    STATE_CHANGE = "state_change"
    TURN_END = "turn_end"
    VERIFY = "verify"
    COMPACTION = "compaction"
    REFLECTION = "reflection"
    REVERTED = "reverted_to"
    ERROR = "error"


@dataclass
class Event:
    type: EventType
    session_id: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """同步发布订阅。UI 订阅渲染，工具/模型层发布事件。"""

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event: Event) -> None:
        for callback in self._subscribers.get(event.type, []):
            callback(event)
```

> **约束**：订阅者抛异常不得影响发布方（用 try/except 包裹并在内部记日志）。
> **约束**：`publish` 必须同步，供 headless 模式确定性断言。

### 2.2 会话与持久化

```python
# src/coderagent/core/session.py
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SessionState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    ERROR = "error"


@dataclass
class Session:
    id: str
    cwd: Path
    created_at: float
    updated_at: float
    state: SessionState = SessionState.IDLE
    model_name: str = ""
    permission_mode: str = "default"
    turn_count: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0      # 没有价格的模型，靠 token 记账
    metadata: dict = field(default_factory=dict)


class SessionStore:
    """JSONL 追加写。事件即事实，重放即状态。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, cwd: Path) -> Session: ...
    def path(self, session_id: str) -> Path: ...
    def append(self, session_id: str, event: Event) -> None: ...
    def events(self, session_id: str) -> list[Event]: ...
    def rebuild(self, session_id: str) -> Session:
        """重放事件得到最新 Session 状态。"""
    def list(self, cwd: Path | None = None) -> list[Session]: ...
```

**文件布局**

```
~/.coderagent/sessions/<session_id>.jsonl     # 事件流
~/.coderagent/sessions/<session_id>.meta.json # 索引元信息（标题、cwd、创建时间）
```

**事件记录格式**（每行一个 JSON 对象）

```json
{"type": "user_message", "session_id": "20261105-a1b2c3", "timestamp": 1762300000.0,
 "payload": {"content": "修复登录超时 bug"}}
```

**会话 ID 规则**：`YYYYMMDD-<6位随机 hex>`，按创建时间排序便于 `list()`。

### 2.3 主循环

```python
# src/coderagent/core/loop.py
class AgentLoop:
    def __init__(self, model: ModelGateway, session: Session,
                 store: SessionStore, bus: EventBus): ...

    def run_turn(self, user_input: str) -> TurnResult:
        """执行一轮：用户输入 → 模型 → 工具 → 直到模型不再请求工具或触发终止。"""

    def run(self, user_input: str) -> TurnResult:
        """多轮：由调用方循环调用 run_turn，Session 维持上下文。"""
```

**TurnResult**

```python
@dataclass
class TurnResult:
    session_id: str
    turn_count: int
    cost: float
    stop_reason: str      # "end_turn" | "max_turns" | "cost_exceeded" | "token_limit" | "error"
    messages: list[dict]  # 本轮新增的消息
    error: str = ""
    session_cost: float = 0.0   # 整个会话的花费（含前面的轮次与结尾那次沉淀）
```

**本轮时序**

```
run_turn(user_input)
  → bus.publish(USER_MESSAGE)
  → store.append(...)
  → while True:
      messages = context.build()            # M0 先返回完整历史
      response = model.query(messages)       # M0 非流式
      bus.publish(ASSISTANT_MESSAGE)
      store.append(...)
      if not response.tool_calls: break      # 模型自然结束
      outputs = executor.execute(response.tool_calls)
      for o in outputs: store.append(TOOL_RESULT)
  → bus.publish(STATE_CHANGE, state=DONE)
```

> **M0 的 `executor` 暂用 `minisweagent` 的 bash 单工具实现**，M1 替换为真正的 ToolRegistry。
> 为此 M0 需要一个薄适配器 `core/bash_adapter.py`，把 `LitellmModel` 的 bash tool_call 转成 `LocalEnvironment.execute`。
> （这个适配器只是临时的：M1 落地后它就被删掉了，今天仓库里已经没有这个文件。）

### 2.4 配置

```python
# src/coderagent/config/schema.py
from pathlib import Path
from pydantic import BaseModel


class ModelConfig(BaseModel):
    model_name: str = ""
    model_kwargs: dict = {}
    max_retries: int = 3
    routing: dict[str, str] = {}      # purpose -> model_name，M4 启用


class AgentConfig(BaseModel):
    max_turns: int = 50
    cost_limit: float = 0.0            # 0 = 不限


class ToolConfig(BaseModel):
    enabled: list[str] = [13 个内置工具名]
    bash_timeout: int = 120
    max_output_tokens: int = 8000


class PermissionConfig(BaseModel):
    mode: str = "default"
    rules: list[dict] = []


class SandboxConfig(BaseModel):
    type: str = "local"                # local|docker|singularity|swerex_*|bubblewrap|contree


class Config(BaseModel):
    model: ModelConfig = ModelConfig()
    agent: AgentConfig = AgentConfig()
    tools: ToolConfig = ToolConfig()
    permissions: PermissionConfig = PermissionConfig()
    sandbox: SandboxConfig = SandboxConfig()
```

> 这段是 M0 的**草图**，实现上后来又改了三处：
> 压缩相关的选项（`auto_compact`、`compact_threshold` 等）搬到了 `ContextConfig`（M2）；
> `ToolConfig.enabled` 的默认值是**全部 13 个内置工具**而不是 `["bash"]`，而且它是一份
> **白名单**——配了就替换默认列表，`tools.disabled` 才是只拿走点名的；
> `SandboxConfig` 里**没有** `network` / `writable_roots` 这类统一开关（见 M4 §13.6），
> 其余选项原样传给底层环境，环境不认识的被忽略。

**四层合并顺序**（后者覆盖前者）

```
config/defaults.yaml  →  项目 .coderagent/config.yaml  →  用户 ~/.coderagent/config.yaml  →  CLI -c key=value
```

复用 `minisweagent.config.get_config_from_spec` 解析单个来源，四层由 `loader.load_config()` 递归合并（`minisweagent.utils.serialize.recursive_merge`）。

---

## 3. 任务分解

### T0.1 包骨架与打包配置
- [x] 创建 `src/coderagent/` 及各级 `__init__.py`
- [x] `pyproject.toml`：`packages.find.include` 加 `coderagent*`
- [x] `pyproject.toml`：`[project.scripts]` 增加 `coder = "coderagent.ui.cli:app"`
- [x] `pyproject.toml`：新增依赖 `tiktoken`（可选 extras，先不装）、`textual` 已在依赖中
- [x] 验证 `pip install -e .` 后 `coder --help` 有输出

**验收**：`python -c "import coderagent"` 成功；`coder --help` 打印帮助。

### T0.2 协议定义
- [x] `core/protocols.py` 定义 `ModelBackend`、`ToolExecutor`
- [x] `ModelBackend`：`query`、`query_stream`、`get_template_vars`
- [x] `ToolExecutor`：`plan(actions) -> list[dict]`、`execute(actions) -> list[dict]`
- [x] 复用 `minisweagent.Environment`（不重复定义）

**验收**：mypy/ruff 无未使用导入；协议方法签名与文档一致。

### T0.3 事件系统
- [x] `EventType` 枚举（见 2.1）
- [x] `Event` dataclass，`to_dict()` / `from_dict()`
- [x] `EventBus.subscribe/publish`
- [x] 订阅者异常隔离

**验收**：`tests/coderagent/test_events.py` — 发布顺序保序；订阅者抛错不影响其他订阅者。

### T0.4 会话与持久化
- [x] `Session` dataclass + `SessionState`
- [x] `SessionStore.create/path/append/events/rebuild/list`
- [x] `rebuild` 重放规则：最后一条 `STATE_CHANGE` 决定 `state`；累加 `total_cost`/`turn_count`
- [x] 会话根目录可用 `MSWEA_CODER_HOME` 环境变量覆盖（便于测试隔离）

**验收**：`tests/coderagent/test_session.py` — 追加 5 条事件后 `rebuild` 得到的 Session 与原 Session 一致；`list()` 按创建时间倒序。

### T0.5 模型网关雏形
- [x] `ModelGateway` 包装 `minisweagent.models.litellm_model.LitellmModel`
- [x] `query(messages)` → 返回规范化的 assistant message dict
- [x] 成本累加进 `Session.total_cost`，并 `bus.publish` 事件
- [x] 复用 `minisweagent.models.utils.retry`

**验收**：用 `ScriptedModel` 替换后端后，query 返回可预测结构。

### T0.6 脚本化测试模型
- [x] `testing/scripted_model.py`：`ScriptedModel(responses: list[dict])`
- [x] 逐次 `query` 弹出下一个响应；耗尽则抛断言错误
- [x] 支持通过 `side_effect` 回调做动态响应（如断言收到的 messages）

**验收**：`tests/coderagent/test_scripted_model.py` — 序列消费正确；耗尽报错清晰。

### T0.7 主循环
- [x] `AgentLoop.run_turn` / `run`
- [x] `core/bash_adapter.py`：bash tool_call → `LocalEnvironment.execute`
- [x] 限额：`max_turns`、`cost_limit`（超限 → `stop_reason="max_turns"`）
- [x] 每轮结束 `store.append` 全部事件

**验收**：集成测试用 `ScriptedModel` 走完「用户提问 → 模型请求 bash → 执行 → 模型收尾」两轮。

### T0.8 配置系统
- [x] `config/schema.py`（见 2.4）
- [x] `config/defaults.yaml`
- [x] `config/loader.py::load_config(specs: list[str], cwd: Path) -> Config`
- [x] 四层合并 + `Config` 校验（非法值给出可读错误）

**验收**：`tests/coderagent/test_config.py` — 四层优先级正确；`model.model_name=x` 覆盖生效。

### T0.9 CLI 与 headless 输出
- [x] `ui/cli.py` typer app，参数见 M3 表格，M0 只实现 `-m/--model -c/--config -t/--task --print --output-format`
- [x] `ui/render.py`：`text`（逐行人类可读）、`json`（单行 JSON，字段 `session_id/messages/cost/session_cost/stop_reason/error`）
- [x] `run.py` 装配：config → model → env → session → loop → renderer

**验收**：`coder --print --output-format json -t "hi" -m <fake>` 输出合法 JSON，含 `session_id` 与 `messages`。

### T0.10 文档与收尾
- [x] `docs/design/` 链接进 mkdocs nav（可选）
- [x] 单元测试跑通 `pytest tests/coderagent -q`
- [x] pre-commit（ruff）通过

---

## 4. 测试计划

| 文件 | 覆盖点 |
|---|---|
| `test_events.py` | 发布保序、订阅者异常隔离、`Event` 序列化往返 |
| `test_session.py` | 事件重放一致性、`list()` 排序、并发追加（单写者） |
| `test_config.py` | 四层优先级、key=value 覆盖、非法值报错 |
| `test_scripted_model.py` | 序列消费、耗尽异常 |
| `test_loop.py` | 单轮/多轮、限额触发、事件全部落盘 |
| `test_cli.py` | `--print --output-format json` 端到端（用 ScriptedModel 注入） |

> **测试纪律**：不 mock 文件系统与 subprocess；用 `tmp_path` + `ScriptedModel` 替代真实模型调用。

---

## 5. 风险

| 风险 | 对策 |
|---|---|
| `SessionStore` 并发写损坏 JSONL | 单进程单写者保证；`append` 用 `"a"` 模式 + 行缓冲 + `flush` |
| 事件类型后续增补导致旧轨迹无法重放 | `rebuild` 对未知 `type` 跳过而非报错；`from_dict` 对未知类型返回 `None`（跳过这一行，不回退成别的类型） |
| 与上游 `minisweagent` 的 Event 概念冲突 | 独立包 `coderagent`，不向 `minisweagent` 引入依赖 |

---

## 6. Definition of Done

- [x] `coder --print -t "..."` 能与模型完成多轮对话（已用 DeepSeek 实跑：读文件 → 改代码 → 跑验证 → 汇报，stdout 为纯 JSON）
- [x] 会话落盘 JSONL，`coder --continue`（M2 实现）之外可手工验证重放
- [x] 单元测试覆盖事件、会话、配置、循环、CLI 五条主线
- [x] ruff / pre-commit 通过
- [x] 依赖边界：仅使用 `minisweagent` 的公开 API（Protocol、config、environments、models.utils）
