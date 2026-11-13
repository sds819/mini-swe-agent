# M2 — 上下文治理与会话管理

> 目标：长会话（100+ 轮）不爆上下文、不丢任务状态；会话可恢复、可分叉、可回滚。
> 依赖：M0（Session/EventBus/Config）、M1（工具输出形态）。
> 后续解锁：M3（TUI 状态栏、压缩提示）、M4（记忆沉淀）。

---

## 1. 交付物清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新增 | `src/coderagent/core/tokens.py` | token 估算器 |
| 新增 | `src/coderagent/core/budget.py` | `BudgetGuard`、输出裁剪 |
| 新增 | `src/coderagent/core/context.py` | `ContextEngine`：构建 prompt、触发压缩 |
| 新增 | `src/coderagent/core/summarize.py` | 结构化摘要 schema + 生成 |
| 新增 | `src/coderagent/core/instructions.py` | 项目指令文件加载（CLAUDE.md / AGENTS.md） |
| 新增 | `src/coderagent/core/memory.py` | 分层记忆读写 |
| 新增 | `src/coderagent/core/checkpoint.py` | 快照与回滚 |
| 新增 | `src/coderagent/core/history.py` | 消息历史抽象（供压缩/裁剪操作） |
| 新增 | `src/coderagent/ui/commands/` | `/compact` `/resume` `/rewind` 等命令实现（M3 接入 UI） |
| 修改 | `src/coderagent/core/loop.py` | 接入 ContextEngine、超限兜底重试 |
| 修改 | `src/coderagent/models/gateway.py` | 捕获 `ContextWindowExceededError` |
| 修改 | `src/coderagent/config/schema.py` | 新增 context / memory / checkpoint 配置 |
| 新增 | `tests/coderagent/core/test_*.py` | 单测 |

---

## 2. 上下文构成

发给模型的完整 messages 数组由 `ContextEngine` 组装：

```
[0] system        角色定义 + 工具规范 + 环境信息（静态，几乎不变）
[1] user          项目指令（CLAUDE.md / AGENTS.md）+ 当前任务 + todo 状态
[2..] history     近期完整轮次（保留窗口内，原样保留 tool results）
[..] summary      早期历史的结构化摘要（1 条 user 消息承载）
```

**组装顺序必须固定**：`summary` 放在 history **之前**（更早的内容），这样因果顺序自然。

### 2.1 ContextEngine 接口

```python
# src/coderagent/core/context.py
class ContextEngine:
    def __init__(self, session: Session, store: SessionStore, bus: EventBus,
                 config: ContextConfig, model: ModelGateway): ...

    def build_messages(self, *, tools: list[dict] | None = None) -> list[dict]:
        """组装要发给模型的 messages。"""

    def maybe_compact(self) -> bool:
        """检查预算，必要时压缩。返回是否发生了压缩。"""

    def force_compact(self) -> bool:
        """强制压缩（用于上下文超限兜底）。"""
```

### 2.2 保留窗口与压缩触发

**触发条件（任一满足）**

1. `estimated_tokens > context_window * compact_threshold`（默认 0.8）
2. `estimated_tokens > context_window - reserved_output`（硬上限，默认预留 8k）
3. 距上次压缩超过 `compact_every_turns`（默认 40 轮，可关闭）

> **注意**：`context.auto_compact` 关掉时，`maybe_compact()` 第一行就返回 `False`，
> 所以条件 3 **永远不会单独成立**——`auto_compact` 是总开关。provider 真的报超限时
> 走的 `force_compact()` 不受这个开关管。

**保留窗口**

```
keep_recent_turns      = 20    # 至少保留最近 20 轮完整消息（含 tool results）
keep_recent_token_ratio = 0.4  # 切完之后剩下的尾巴至少要占窗口的 40%
```

> 取「轮数」与「token 占比」里**保留得更多**的那个：轮数少但每轮很大时靠 token 兜底，
> 轮数多但很小时靠轮数兜底。注意 `keep_recent_token_ratio` 是**下限**——切完之后剩下的
> 尾巴若不足这个比例，就把切点再往前挪（甚至不切）。

**压缩后必须保留**（不可被摘要吞掉）

- 最近一次 `todo_write` 的状态
- 当前会话的 `files_touched` 清单
- 未完成的报错信息（最后 3 条 `is_error` 结果）

### 2.3 结构化摘要

**摘要 schema**（JSON，存于 `Session.metadata["summary"]`）

```json
{
  "goal": "用户当前要达成什么（一句话）",
  "findings": ["已确认的事实，含 file:line"],
  "decisions": ["已做的技术决策及理由"],
  "files_touched": [{"path": "src/cache.py", "change": "新增 Redis 缓存层", "state": "modified"}],
  "open_questions": ["尚未解决的问题"],
  "next_steps": ["明确的下一步"],
  "errors_seen": ["已遇到并解决的错误"]
}
```

**生成方式**

- 用 `ModelGateway.complete(purpose="summarize")` 走廉价模型
- Prompt 明确要求输出上表 JSON，字段缺失填 `[]` 而非省略
- 解析失败 → 重试一次；仍失败 → 退化为「取保留窗口之前的最后 N 条消息原文拼接」的保守摘要（保底不崩）

**注入方式**

摘要作为一条 `user` 消息插入：

```
<session_summary>
以下是被压缩的早期对话摘要，请保留这些事实继续工作。

goal: ...
findings:
- ...
files_touched:
- src/cache.py (modified): 新增 Redis 缓存层
open_questions:
- ...
</session_summary>
```

**关键校验**：压缩后 `files_touched` 必须非空（除非确实没改过文件）。若模型返回空但历史里有编辑类工具调用，则视为摘要失败 → 回退保守摘要。

### 2.4 Token 估算与预算

```python
# src/coderagent/core/tokens.py
def estimate_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    """无 tokenizer 时的启发式估算：字符数 / 3.6 + 每条消息固定开销 4。"""
```

- 若 `tiktoken` 已安装 → 用 `tiktoken.get_encoding("cl100k_base")` 精确估算
- 估算值用于**决策**（是否压缩），实际是否超限由 API 报错兜底

```python
# src/coderagent/core/budget.py
@dataclass
class BudgetGuard:
    context_window: int = 200000
    reserved_output: int = 8000
    compact_threshold: float = 0.8

    def should_compact(self, estimated: int) -> bool: ...
    def limit(self) -> int:
        """可用于上下文的 token 预算。"""
```

### 2.5 工具输出裁剪

M1 的裁剪按字符，M2 改为按 token：

```
if tokens(output) <= max_output_tokens: 原样返回
else: 保留头 40% + 尾 40%，中间插入：
      "... [N lines, M tokens elided] ..."
      并追加提示："Use grep/offset to view the specific region."
```

裁剪结果**同时**写入 `Session.metadata["truncated_outputs"]`（路径 + 行号范围），便于模型用 `read(offset=)` 精确回看。

### 2.6 上下文超限兜底

```
AgentLoop._query()
  └─ 捕获上下文溢出异常（models/gateway.py 的 is_context_overflow）
      → ContextEngine.force_compact()
      → 重发一次（最多 1 次）
      → 仍失败 → 返回错误，stop_reason="error"
```

这是真实使用中最高频的失败模式，**必须**有兜底。
注意判溢出不只看异常类型：provider 把「context window」「context_length_exceeded」
写进消息里时也算（`is_context_overflow`）。压不动时错误消息里会带 "nothing left to compact"。

### 2.7 项目指令文件

**加载顺序**

```
1. ~/.coderagent/CLAUDE.md            （用户级）
2. <cwd>/AGENTS.md 或 <cwd>/CLAUDE.md （项目级，两者都存在则都加载，AGENTS 优先）
3. <cwd>/<子目录>/AGENTS.md           （进入该目录时追加，Claude Code 风格）
```

**注入**：作为一个独立的 `user` 消息区块，放在任务描述之前：

```
<project_instructions source="AGENTS.md">
...内容...
</project_instructions>
```

**子目录指令**：采用「惰性加载」——当 `bash`/`read`/`grep` 的目标落在某个子目录时，把该子目录的 `AGENTS.md` 追加进上下文（同一文件只注入一次）。

### 2.8 分层记忆

| 层 | 作用域 | 存储 | 生命周期 |
|---|---|---|---|
| 工作记忆 | 当前 turn | 内存（`Session.metadata`） | 单轮 |
| 会话记忆 | 当前 session | `SessionStore` + `Session.metadata["summary"]` | 单会话 |
| 项目记忆 | 项目 | `.coderagent/memory/*.md` | 长期，需显式写入 |
| 用户记忆 | 跨项目 | `~/.coderagent/CLAUDE.md` | 长期，需显式写入 |

**M2 只实现读**：项目/用户记忆文件作为指令的一部分注入（与 2.7 合并）。
**写入（经验沉淀）放到 M4**。

### 2.9 检查点与回滚

**快照内容**

```python
@dataclass
class Checkpoint:
    id: str
    timestamp: float
    turn: int
    kind: str          # "file_diff" | "container_commit"
    payload: dict      # file_diff: {path: old_content}；container: {image: "sha256:..."}
```

**实现**

- **file_diff**：在每次写类工具执行前，读取目标文件的旧内容存入 checkpoint（内存 + 落盘 `checkpoints.json`）。轻量、够用。
- **container_commit**：Docker 环境下 `docker commit`（重，M3+ 可选启用）。

**回滚 `/rewind`**

- 选择 checkpoint → 恢复被改文件的旧内容 → 删除新建的文件
- 上下文历史也需回滚：写一条 `REVERTED`（`reverted_to`）事件，重放时按它截断历史
  （不物理删除日志里的消息）

**保留策略**：最近 `keep` 个 checkpoint（默认 50，`context.checkpoint.keep`）。

### 2.10 会话恢复与分叉

| 命令 | 行为 |
|---|---|
| `coder --resume <id>` | 载入会话，从头重放事件恢复状态，继续对话 |
| `coder --continue` | 载入当前目录下最近一个会话 |
| `coder --fork <id>` | 复制会话为新 id，从当前点继续（保留原会话） |
| `coder --list` | 列出历史会话（id、标题、时间、cwd、轮数、成本） |

**重放实现**：`SessionStore.rebuild(id)` 重放事件 → 得到 Session + 消息历史。

---

## 3. 任务分解

### T2.1 Token 估算
- [x] `estimate_tokens(messages, tools)`
- [x] 有 `tiktoken` 用精确，否则启发式
- [x] 工具 schema 计入估算

**验收**：启发式估算误差在典型样本 ±20% 内（有单测用固定样本标定常数）。

### T2.2 预算守卫
- [x] `BudgetGuard.should_compact` / `limit`
- [x] 配置项：`context_window`（按模型名查表，默认 200k）、`reserved_output`、`compact_threshold`

### T2.3 历史抽象
- [x] `core/history.py`：`History` 持有消息列表，提供 `recent_turns(n)`、`split_at(index)`、`token_count()`
- [x] 「一轮」的界定：**一条 `user` 消息** + 模型为它做的一切（assistant 消息 + 后续工具结果）

**验收**：`test_budget_history.py` — 按轮切分正确；`split_at` 后拼接等于原列表。

### T2.4 上下文组装
- [x] `ContextEngine.build_messages` 按 2.0 的固定顺序组装
- [x] summary 插在 history 之前
- [x] 保留窗口逻辑（轮数 / token 占比取大）
- [x] todo 状态注入

### T2.5 结构化摘要
- [x] `summarize.py`：schema 定义 + 生成 prompt + JSON 解析
- [x] 解析失败重试一次 → 保守摘要回退
- [x] `files_touched` 空值校验 → 触发回退
- [x] 摘要注入为 `user` 消息（`<session_summary>` 包裹）

**验收**：`test_summarize.py` — 正常摘要、非法 JSON 回退、files_touched 缺失回退。

### T2.6 压缩触发与执行
- [x] `maybe_compact()`：三种触发条件
- [x] `force_compact()`
- [x] 压缩事件落盘（`EventType.COMPACTION`），记录被压缩消息数与 token 数

### T2.7 输出裁剪升级
- [x] 按 token 裁剪（替换 M1 的字符裁剪）
- [x] 记录 `truncated_outputs`（path + 行范围）

### T2.8 上下文超限兜底
- [x] `ModelGateway` 捕获 `ContextWindowExceededError`
- [x] `AgentLoop` 强制压缩后重发一次
- [x] 二次失败 → 停止并报错

### T2.9 项目指令加载
- [x] `instructions.py::load_instructions(cwd, user_home) -> list[InstructionBlock]`
- [x] 优先级：用户 < 项目 < 子目录
- [x] 注入为 `<project_instructions source="...">` 块
- [x] 子目录指令惰性加载（bash/read/grep 命中子目录时）

### T2.10 检查点
- [x] `checkpoint.py`：`Checkpoint` dataclass + `CheckpointStore`
- [x] 写类工具执行前自动创建 checkpoint（hook 进 Executor）
- [x] `/rewind` 回滚文件内容 + 标记历史回滚

### T2.11 会话恢复/分叉
- [x] `--resume` / `--continue` / `--fork` / `--list`
- [x] `SessionStore.rebuild` 支持重放出消息历史

### T2.12 命令实现
- [x] `ui/commands/compact.py`（手动压缩）
- [x] `ui/commands/resume.py`（列出与选择）
- [x] `ui/commands/rewind.py`（检查点选择与回滚）
- [x] 命令以「纯函数 + 事件」形式实现，M3 由 TUI 调用

### T2.13 配置扩展
- [x] `ContextConfig`：`context_window`、`compact_threshold`、`reserved_output`、`keep_recent_turns`、`keep_recent_token_ratio`、`compact_every_turns`、`auto_compact`、`summarize_model`、`summary_chunk_tokens`
- [x] `MemoryConfig`：项目/用户记忆路径
- [x] `CheckpointConfig`：`enabled`、`keep`

---

## 4. 测试计划

| 文件 | 覆盖点 |
|---|---|
| `core/test_tokens.py` | 估算器在固定样本上的标定；有/无 tiktoken 两条路径 |
| `core/test_budget_history.py` | 按轮切分、split 往返、token 计数 |
| `core/test_context.py` | 消息组装顺序、保留窗口、summary 位置 |
| `core/test_summarize.py` | schema 解析、重试、两种回退路径、files_touched 校验 |
| `core/test_compaction.py` | 三种触发条件、压缩后 token 下降、事件落盘 |
| `core/test_overflow.py` | 模拟超限异常 → 强制压缩 → 重发成功 |
| `core/test_instructions.py` | 优先级、子目录惰性加载、去重 |
| `core/test_checkpoint.py` | checkpoint 创建、回滚文件内容、保留策略 |
| `core/test_resume.py` | resume/fork/list 一致性 |
| `test_long_session.py` | 200 轮模拟会话，断言从未超过预算 |

---

## 5. 风险

| 风险 | 对策 |
|---|---|
| 摘要质量不稳定，模型丢失任务状态 | 结构化字段强制 + `files_touched` 非空校验 + 保守回退；保留 todo 与最近错误 |
| 压缩时机不当（过早压缩丢信息） | 阈值默认 0.8，且「轮数/token 占比取大」保留足够上下文 |
| 重放不一致（事件类型扩展） | 未知事件类型跳过；`rebuild` 只依赖已知字段 |
| 回滚与外部副作用不一致（装了依赖、跑了命令） | 检查点只回滚文件；命令副作用不可回滚，在回滚提示中明确告知 |
| token 估算偏差导致仍超限 | 兜底重试路径 + 硬上限二次触发 |

---

## 6. Definition of Done

- [x] 200 轮模拟会话全程不超预算，压缩后 token 数显著下降
- [x] 压缩后模型仍能说出「改了哪些文件、还剩什么问题」
- [x] 上下文超限异常能被自动兜底（压缩 + 重发）
- [x] `coder --resume` 能恢复并继续对话；`--fork` 不影响原会话
- [x] `/rewind` 能把文件恢复回上一检查点
- [x] 项目指令文件按优先级正确注入

---

## 7. 实现说明（与原设计的偏差）

| 项 | 设计 | 实现 | 原因 |
|---|---|---|---|
| 上下文窗口 | 固定保留最近 20 轮，窗口外的直接丢掉 | 发给模型的是「上次压缩以来的全部历史」，保留窗口只在**压缩时**决定切点 | 固定窗口会静默丢轮次。改成只有压缩才缩短历史，被缩短的内容先进摘要，一句都不丢 |
| 保留规则 | 轮数与 token 占比取大 | 同左，但切点之后还有一道硬上限 `context_window - reserved_output` | 保证实际发出的上下文一定不超预算；200 轮模拟全程守住了这条线 |
| 摘要存放 | `Session.metadata["summary"]` | 独立事件 `EventType.COMPACTION` 承载，`restore()` 重放时还原 | 事件日志是唯一事实来源；`metadata` 在压缩时会自相矛盾 |
| 多次压缩 | 每次生成一份新摘要 | 新摘要的输入里带上上一份摘要，输出始终只有一份 | 否则摘要会越堆越多，把预算吃光（200 轮测试里出现过） |
| 压缩触发条件 2 | 硬上限单独一条 | 并入 `BudgetGuard.should_compact`（取 `min(阈值, 硬上限)`） | 两者都是「超过某个上限」，合并后行为等价、逻辑更少 |
| 上下文窗口大小 | 按模型名查表 | 同左，但**只在配置未显式设置**时生效 | 显式配置永远优先；默认 200k，未知模型也走 200k |
| 摘要模型 | `ModelGateway.complete(purpose="summarize")` | `ContextEngine(summary_model=...)`，摘要调用不带工具 | 摘要不需要工具；`summarize_model` 留空时走**路由里的 `summarize` 用途**（那个用途没配就回落主模型） |
| `recent_errors` | schema 里没有 | `Summary` 多一个派生字段，渲染在 `errors_seen` 之后 | 「最近 3 条报错」要保留，但不该由模型自己填 |
| 检查点存储 | 单个 `checkpoints.json` | 每个会话一个 JSON 文件，`CheckpointStore.all()` 读取 | 便于按会话只留最近 `keep` 个 |
| 回滚 | 恢复文件 + 标记历史「已撤销」 | 同左，历史用 `EventType.REVERTED` 截断而非物理删除 | 重启后仍能重放出同样的历史 |
| 命令 | `/compact` `/resume` `/rewind` | `ui/commands/` 下的纯函数 + 事件，M3 由 TUI 调用 | 与设计一致，只是 CLI 暂未接线（M3） |
| 子目录指令 | bash/read/grep 命中子目录时加载 | `Executor` 的 `on_path` 回调 → `ContextEngine.note_path()` | 命中的是工具的目标路径，不一定是 bash 命令里的字符串 |

**实测**（DeepSeek，`deepseek/deepseek-flash`）：

- 真实会话里模型建了 `gamma.py` 并运行验证；压缩后追问「改了哪些文件」，模型准确答出 `gamma.py`，并说明 `alpha.py`/`beta.py` 只读未改。
- 真实 provider 会拒绝空的 `tool_calls` 数组（`BadRequestError: empty array`），后端归一化时改为不带该字段。
