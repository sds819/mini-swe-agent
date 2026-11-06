# M1 — 工具系统与权限

> 目标：模型能用结构化工具（read / write / edit / glob / grep / ls / todo_write）读写代码；写操作与危险 bash 受权限策略控制。
> 依赖：M0（Session/EventBus/Loop/Config 已就位）。
> 后续解锁：M2（上下文治理）、M3（审批 UI、diff 预览）。

---

## 1. 交付物清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `src/coderagent/tools/base.py` | `Tool` 协议、`ToolResult`、`ToolContext` |
| 新增 | `src/coderagent/tools/registry.py` | `ToolRegistry`：注册、schema 生成、预算裁剪 |
| 新增 | `src/coderagent/tools/executor.py` | `ToolExecutor`：解析 → 权限 → 执行 → 结果回填 |
| 新增 | `src/coderagent/tools/permissions.py` | `PermissionMode`、`Rule`、`PermissionPolicy` |
| 新增 | `src/coderagent/tools/builtin/fs.py` | `read` `write` `edit` `multi_edit` |
| 新增 | `src/coderagent/tools/builtin/search.py` | `glob` `grep` `ls` |
| 新增 | `src/coderagent/tools/builtin/shell.py` | `bash`（包装 minisweagent LocalEnvironment） |
| 新增 | `src/coderagent/tools/builtin/todo.py` | `todo_write` `update_plan` |
| 新增 | `src/coderagent/tools/builtin/__init__.py` | 内置工具注册表 |
| 新增 | `src/coderagent/tools/rules.py` | 规则文件加载与合并 |
| 修改 | `src/coderagent/core/loop.py` | 接入 ToolExecutor，替换 bash 适配器 |
| 修改 | `src/coderagent/config/schema.py` | 扩展 `ToolConfig`、`PermissionConfig` |
| 新增 | `tests/coderagent/tools/test_*.py` | 工具与权限单测 |

---

## 2. 核心抽象

### 2.1 Tool

```python
# src/coderagent/tools/base.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]      # JSON Schema

    def run(self, params: dict[str, Any], ctx: "ToolContext") -> ToolResult: ...


@dataclass
class ToolContext:
    cwd: Path
    session: Session
    bus: EventBus
    policy: PermissionPolicy
    config: ToolConfig
    env: Environment                 # bash 等需要执行环境的工具
```

**约定**：工具自身**不做**权限判断（由 Executor 统一做），也**不**做路径越界防护（由 Policy 用 cwd 相对路径判断）；但工具**必须**对自身参数做类型/存在性校验，返回 `is_error=True` 而不是抛异常。

### 2.2 Registry

```python
# src/coderagent/tools/registry.py
class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None): ...
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def schemas(self, budget_tokens: int | None = None) -> list[dict]:
        """生成 OpenAI 兼容 tools 参数；budget 不足时按优先级丢弃低频工具。"""
```

**工具 schema 生成**

```python
{"type": "function",
 "function": {"name": "edit",
              "description": "...",
              "parameters": {"type": "object", "properties": {...}, "required": [...]}}}
```

**优先级（用于预算裁剪，从先丢弃到最后丢弃）**

```
web_search → web_fetch → todo_write → multi_edit → write → edit → ls → glob → grep → read → bash
```

> `bash` 与 `read` 永不丢弃：前者是兜底，后者是主力。

**Schema token 估算**：`len(json.dumps(schema)) / 3.5`（启发式），M2 换精确 tokenizer。

### 2.3 Executor：模型 tool_call → 执行

```python
# src/coderagent/tools/executor.py
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy,
                 ctx_factory: Callable[[], ToolContext],
                 approver: "Approver | None" = None): ...

    def execute(self, tool_calls: list[dict]) -> list[dict]:
        """返回可直接作为 API 消息的 observation 列表。"""
```

**流程**

```
for tool_call in tool_calls:
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    tool = registry.get(name)
    if tool is None:              → is_error 消息 "Unknown tool 'x'. Available: ..."
    decision = policy.check(name, args)
    if decision == "deny":        → is_error 消息（不回传原文）
    if decision == "ask":         → approver.request(...) → allow / deny / always
    result = tool.run(args, ctx)
    → 组装 {role: "tool", tool_call_id, content: result.content}
```

**并行执行**：模型一次返回多个 tool_call 且**互不依赖**时并行执行。

依赖判定（保守）：
- 写类工具（`write` `edit` `multi_edit`）与任何工具同时出现 → 顺序执行
- `bash` 与其他工具同时出现 → 顺序执行
- 其余（`read` `glob` `grep` `ls` `todo_write`）→ 并行

用 `concurrent.futures.ThreadPoolExecutor`，结果按**原始 tool_call 顺序**重排（API 要求顺序对应）。

**错误消息原则**：工具失败要以「模型可自我修正」的方式反馈。例如 `edit` 失败时返回：
```
Error: old_string not found in src/a.py.
The file contains 3 occurrences of "foo"; old_string must be unique.
Use `read` to view the exact content, then retry with more surrounding context.
```

### 2.4 权限策略

```python
# src/coderagent/tools/permissions.py
from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    DEFAULT = "default"           # 读 allow；写与 bash ask
    ACCEPT_EDITS = "acceptEdits"  # 文件编辑 allow；bash ask
    PLAN = "plan"                 # 全部只读；一切写操作 deny
    BYPASS = "bypass"             # 全 allow
    READONLY = "readonly"         # 仅 read/glob/grep/ls allow，其余 deny


@dataclass
class Rule:
    tool: str = "*"          # 工具名或 "*"
    pattern: str = "*"       # 对 path / command 的 glob（path）或 regex（command）
    decision: str = "ask"    # allow | ask | deny
    reason: str = ""


class PermissionPolicy:
    def __init__(self, mode: PermissionMode, rules: list[Rule]): ...

    def check(self, tool: str, params: dict) -> str:
        """返回 allow / ask / deny，并记录命中的规则。"""
```

**求值顺序**

1. `mode` 决定默认值（见 2.4 表）
2. 遍历规则，**最后命中者生效**（后写规则覆盖先写）
3. 但 `deny` 一票否决：只要有规则命中 `deny` 且未被后续 `allow` 覆盖…

> **简化决策**：采用「最后命中者生效」，规则顺序即优先级。文档中明确「把 deny 规则放在文件末尾可覆盖前面的 allow」。这比「deny 优先」更可预测，也更符合 Claude Code 的 `.claude/settings.json` 语义（后写覆盖）。

**默认规则表**

| mode | read/glob/grep/ls | write/edit/multi_edit | bash | 其他 |
|---|---|---|---|---|
| DEFAULT | allow | ask | ask | ask |
| ACCEPT_EDITS | allow | allow | ask | ask |
| PLAN | allow | deny | deny | deny |
| READONLY | allow | deny | deny | deny |
| BYPASS | allow | allow | allow | allow |

**匹配目标**

- 路径类工具（`write` `edit` `multi_edit`）：匹配 `path` 参数，相对 `cwd` 解析后用 `fnmatch` + `**` 语义
- `bash`：匹配 `command` 字符串，用**正则**（默认 `re.search`）
- 其他工具：匹配工具名本身

**路径越界**：任何解析后落在 `cwd` 之外的路径（`../` 逃逸或绝对路径）→ `deny`，除非该路径命中显式 allow 规则（如 `include_dirs`）。

### 2.5 Approver 抽象（UI 无关）

```python
# src/coderagent/tools/permissions.py
class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALWAYS = "always"


class Approver(Protocol):
    def request(self, tool: str, params: dict, reason: str) -> ApprovalDecision: ...
```

- **TUI 实现**（M3）：弹窗交互
- **headless 实现**（M1 即需）：`--permission-mode bypass` 或检测到非 TTY → 自动 `DENY` 并在结果里说明「非交互环境需要显式授权」，避免卡死
- `ALWAYS` → 由 `rules.py` 写入用户级规则文件 `~/.coderagent/rules.yaml`

---

## 3. 内置工具规范

### 3.1 `read`

参数：`path`（必填）、`offset`（int，默认 1）、`limit`（int，默认 2000 行）

行为：
- 相对 `cwd` 解析；路径不存在 → 错误消息提示 `ls` 该目录
- 二进制文件 → 错误「binary file」
- 输出带行号：`   12\tcontent`（对齐右对齐宽度）
- 超出 `limit` → 末尾追加 `... (showing lines 1-2000 of 15234, use offset=2001 to continue)`
- 行宽截断：单行超过 2000 字符 → 截断并标注

### 3.2 `write`

参数：`path`（必填）、`content`（必填）

行为：
- 文件已存在 → 覆写（权限层负责拦截）
- 自动创建父目录
- 写入前记录旧内容，供 checkpoint 使用
- 返回 `Created <path> (N lines)` / `Updated <path> (N lines)`

### 3.3 `edit`

参数：`path`（必填）、`old_string`（必填）、`new_string`（必填）、`replace_all`（bool，默认 False）

行为：
- `old_string` 必须**唯一**；出现 0 次 → 错误「not found」；出现 >1 次 → 错误并给出出现次数与行号
- 换行归一：文件用 CRLF 时按实际内容匹配
- 成功返回：替换行数 + 新增行数 + 变更摘要（前 5 行 diff）
- 附带 `metadata.diff`（unified diff），供 M3 的 diff 预览与 checkpoint 使用

> **为什么必须唯一**：这是 mini-swe-agent 用 `sed` 的主要风险点。唯一匹配把「模糊替换」变成「精确替换」，误改概率大幅下降。

### 3.4 `multi_edit`

参数：`path`（必填）、`edits`（数组，每项 `{old_string, new_string, replace_all?}`）

- 依次应用，每步都做唯一性校验；任一步失败 → 整体回滚（先读全文件在内存改，全部成功才落盘）
- 返回每个 edit 的结果

### 3.5 `glob`

参数：`pattern`（必填）、`path`（可选，搜索根）

- 语义同 `git ls-files`/`find` 的 glob：`**` 跨目录，`*` 不跨 `/`
- 结果排序：路径字典序；默认上限 200 条，超出截断并提示
- 忽略目录：`.git`、`node_modules`、`__pycache__`、`.venv`

### 3.6 `grep`

参数：`pattern`（必填，正则）、`path`（可选）、`glob`（可选，限定文件名）、`output_mode`（`content`|`files_with_matches`|`count`，默认 `content`）、`-i`（bool）

- 优先 `rg`（`rg --json` 不需要，用普通模式即可），无 `rg` 时回退 `grep -rn`
- 输出格式：`path:line:content`
- 默认最多 100 条匹配，超出截断并提示用更精确的 pattern
- 二进制文件跳过

### 3.7 `ls`

参数：`path`（可选，默认 cwd）、`depth`（默认 1）

- 输出：目录项 + 类型标记（`d`/`f`）+ 大小
- 非递归（`depth=1`）；`depth=-1` 递归

### 3.8 `bash`

参数：`command`（必填）、`timeout`（可选，覆盖默认）、`run_in_background`（bool，默认 False）

- 复用 `minisweagent.environments.local.LocalEnvironment.execute`（`subprocess.run` + 进程组超时 kill）
- `run_in_background=True` → 立即返回 `task_id`，用 `bash_output(task_id)` / `bash_kill(task_id)` 后续取（长跑测试用）
- 输出按 `max_output_tokens` 裁剪（头尾保留，中间标注省略行数）
- **保留 mini 的 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 语义**？→ 不保留。coding agent 的终止由模型自身的 stop_reason 决定，不依赖 shell 魔数。

### 3.9 `todo_write` / `update_plan`

参数：`todos`（数组，每项 `{content, status, activeForm?}`）

- 状态写进 `Session.metadata["todos"]`
- 每次变更 `bus.publish(TOOL_RESULT)`，供 TUI 渲染任务面板
- `update_plan` 与 `todo_write` 二选一实现即可（M1 先做 `todo_write`）

---

## 4. 规则文件

```yaml
# .coderagent/rules.yaml （项目级）
rules:
  - tool: bash
    pattern: "git (status|diff|log)\\b.*"
    decision: allow
    reason: 只读 git 操作
  - tool: write
    pattern: "**/secrets/**"
    decision: deny
    reason: 禁止写入密钥文件
  - tool: bash
    pattern: "rm -rf\\s+/"
    decision: deny
    reason: 危险删除
```

```yaml
# ~/.coderagent/rules.yaml （用户级，会被「总是允许」写入）
rules:
  - tool: bash
    pattern: "pytest -k .*"
    decision: allow
```

**合并顺序**（后者覆盖前者，按 `tool`+`pattern` 视为同一条）
```
内置默认 → 项目规则 → 用户规则 → 「总是允许」写入
```

---

## 5. 任务分解

### T1.1 工具抽象与上下文
- [x] `tools/base.py`：`Tool`、`ToolResult`、`ToolContext`
- [x] `ToolContext` 由 `ctx_factory` 延迟构造（避免循环依赖）

**验收**：`tests/coderagent/tools/test_base.py` — `ToolResult` 默认值与 metadata 行为。

### T1.2 注册表
- [x] `register/get/schemas`
- [x] 名称冲突：后注册覆盖前注册并告警
- [x] `schemas(budget_tokens)` 按优先级裁剪，`bash`/`read` 不可裁剪

**验收**：注册 3 个工具后 `schemas()` 返回合法 OpenAI 格式；budget=0 时只剩 bash/read。

### T1.3 文件工具
- [x] `read`（行号、offset/limit、二进制检测、长行截断）
- [x] `write`（建目录、记录旧内容供 checkpoint）
- [x] `edit`（唯一性校验、CRLF、返回 diff）
- [x] `multi_edit`（原子性：内存改全量后再落盘）

**验收**：`test_fs.py` — edit 在 0 次 / >1 次出现时返回 `is_error`；multi_edit 中途失败时文件内容不变。

### T1.4 搜索工具
- [x] `glob`（`**` 语义、忽略目录、200 条上限）
- [x] `grep`（rg 优先 / grep 回退、三种 output_mode、100 条上限）
- [x] `ls`

**验收**：`test_search.py` — 用 `tmp_path` 建真实目录树验证 glob/grep 结果。

### T1.5 Shell 工具
- [x] `bash` 包装 `LocalEnvironment`
- [x] 输出按 token 裁剪
- [x] `run_in_background` + `bash_output` / `bash_kill`

**验收**：`test_shell.py` — 超时命令被进程组 kill，无孤儿进程。

### T1.6 Todo 工具
- [x] `todo_write` 写入 `Session.metadata`
- [x] 发布事件供 UI 订阅

### T1.7 权限策略
- [x] `PermissionMode`、`Rule`、`PermissionPolicy.check`
- [x] 五种 mode 的默认规则表
- [x] 路径类用 fnmatch glob；bash 用正则
- [x] 路径越界检测（`cwd` 外默认 deny）
- [x] `check` 返回命中规则（供 UI 解释「为什么被拦」）

**验收**：`test_permissions.py` — 参数化覆盖五种 mode × 六类工具；规则「后写覆盖」语义；`deny` 命中。

### T1.8 规则文件加载
- [x] `rules.py::load_rules(project_dir, user_home) -> list[Rule]`
- [x] 校验规则格式，非法规则给出明确报错并指出文件与行号

### T1.9 Executor
- [x] 解析 tool_call → 规范化 action（含 `tool_call_id`）
- [x] 未知工具 → 友好错误 + 可用工具列表
- [x] 参数 JSON 解析失败 → 友好错误
- [x] 权限决策流程（deny/ask/allow）
- [x] 顺序执行 + 并行执行（依赖判定见 2.3），结果按原序重排

**验收**：`test_executor.py` — 并行结果的 `tool_call_id` 顺序与输入一致；deny 时不执行工具。

### T1.10 Approver 与 headless 行为
- [x] `HeadlessApprover`：非 TTY → DENY；`bypass` → ALLOW
- [x] `AlwaysAllowApprover`：写用户级规则文件

### T1.11 接入主循环
- [x] `AgentLoop` 用 `ToolExecutor` 替换 bash 适配器
- [x] `ToolExecutor` 通过 `ctx_factory` 拿当前 Session/Policy
- [x] `permissions.mode` 从配置注入

### T1.12 配置扩展
- [x] `ToolConfig`：`enabled`、`bash_timeout`、`max_output_tokens`、`include_dirs`
- [x] `PermissionConfig`：`mode`、`rules`、`deny_paths`

### T1.13 端到端验证
- [x] `ScriptedModel` 驱动一次「read → edit → grep」任务，断言文件内容真实改变
- [x] 一次「edit 越界路径」任务，断言被拒绝且文件未变

---

## 6. 测试计划

| 文件 | 覆盖点 |
|---|---|
| `tools/test_base.py` | ToolResult、ToolContext |
| `tools/test_registry.py` | schema 生成、预算裁剪、冲突处理 |
| `tools/test_fs.py` | read/write/edit/multi_edit 全部失败分支（不存在、0 次、多次、二进制、CRLF） |
| `tools/test_search.py` | glob `**` 语义、grep 三模式、上限截断 |
| `tools/test_shell.py` | 正常、超时、后台任务 |
| `tools/test_permissions.py` | 五 mode × 工具矩阵、规则覆盖顺序、路径越界 |
| `tools/test_executor.py` | 并行顺序、未知工具、参数错误、deny 不执行 |
| `tools/test_rules.py` | 规则文件解析、非法规则报错 |
| `test_loop_tools.py` | 端到端多工具任务 |

---

## 7. 风险

| 风险 | 对策 |
|---|---|
| 模型在专用工具与 bash 之间摇摆 | 工具描述写清边界；system prompt 给「优先用专用工具，bash 用于复杂流水线」的指引 |
| 并行执行的写冲突 | 保守依赖判定：任何写类或 bash 参与即顺序执行 |
| 路径匹配语义（`**`）实现偏差 | 只实现两层语义（`*` 不跨 `/`，`**` 跨 `/`），单测锁定 |
| 「总是允许」规则文件被污染 | 写入前校验，写入后回读确认；用户级文件独立于项目文件 |
| headless 下 ask 卡死 | `HeadlessApprover` 默认 DENY 而非阻塞 |

---

## 8. Definition of Done

- [x] 模型可完成「读文件 → 定位 → 编辑 → 验证」的完整任务，文件真实变更
- [x] 写操作与 bash 按权限模式正确 allow/ask/deny
- [x] headless 模式遇到 ask 不挂起
- [x] `edit` 的唯一匹配约束有测试锁定
- [x] 并行执行结果顺序与 tool_call 输入一致
- [x] ruff / pre-commit 通过

---

## 9. 实现说明（与原设计的偏差）

| 项 | 设计 | 实现 | 原因 |
|---|---|---|---|
| `grep` | 优先 `rg`，回退 `grep -rn` | 纯 Python 实现 | `rg` 在非交互 shell 里常常不在 PATH 上，纯 Python 保证各机器行为一致，也省掉子进程 |
| `include_dirs` | 属于 `ToolConfig` | 属于 `PermissionConfig` | 它只影响路径越界判定，与权限策略同源 |
| `todo_write` / `bash_output` / `bash_kill` | 未在默认规则表中 | 归入 `INFO_TOOLS`，任何模式都 allow | 它们只动 agent 自己的记账，不碰仓库，无需审批 |
| `update_plan` | 与 `todo_write` 二选一 | 只做 `todo_write` | 两者语义重合，M2 再决定是否需要单独的 plan 视图 |
| 审批 | M3 才有 TUI | M1 就是 `HeadlessApprover`（ask → DENY） | headless 不能阻塞；交互式审批留给 M3 |

**实测**（DeepSeek，`coder --print --permission-mode acceptEdits`）：
模型连续调用 `read` → `edit` → `grep`，文件真实被改写；默认权限模式下 `edit` 被拒并把原因回传给模型，模型据此改口而不是硬改。
