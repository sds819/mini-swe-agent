# M4 — 进阶能力

> 目标：把 coding agent 从「一个人用的 CLI」升级为「可扩展、可分工、可学习的系统」。
> 依赖：M0–M3 全部完成。
> 本里程碑多为可选功能，可按需裁剪。

---

## 1. 功能范围

| 编号 | 功能 | 优先级 | 说明 |
|---|---|---|---|
| F4.1 | 子 Agent 委派 | P0 | `task` 工具，独立上下文执行子任务 |
| F4.2 | 子 Agent 定义文件 | P0 | `.coderagent/agents/*.md` |
| F4.3 | 多模型路由策略 | P1 | 按 purpose / 难度 / 成本自动选模型 |
| F4.4 | 经验沉淀 | P1 | 会话结束写项目/用户记忆 |
| F4.5 | Skills 系统 | P2 | 可复用的能力包（带资源文件与脚本） |
| F4.6 | 插件机制 | P2 | 第三方扩展的发现与加载 |
| F4.7 | 远程沙箱 | P2 | 复用 mini 的 swerex / modal / contree |
| F4.8 | 可观测性 | P1 | trace 导出、指标、成本归因 |

---

## 2. F4.1 / F4.2 子 Agent 委派

### 2.1 动机

某些子任务（跑遍全仓找某个符号、批量改同一模式、调研某个第三方库）会**污染主上下文**——大量中间输出占满预算。委派给子 agent，主 agent 只接收结论。

### 2.2 `task` 工具

```python
# src/coderagent/tools/builtin/task.py
@dataclass
class SubagentSpec:
    name: str
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=lambda: ["read", "grep", "glob", "bash"])
    model_purpose: str = "cheap"
    max_turns: int = 20
```

**工具签名**

```json
{
  "name": "task",
  "description": "委派一个独立子任务给子 agent。子 agent 在独立上下文中执行，返回结构化结论。适合：全仓搜索、批量重构调研、独立验证。",
  "parameters": {
    "type": "object",
    "properties": {
      "subagent_type": {"type": "string", "description": "子 agent 类型名"},
      "description": {"type": "string", "description": "任务的完整描述（子 agent 看不到主会话上下文）"},
      "prompt": {"type": "string", "description": "给子 agent 的具体指令"}
    },
    "required": ["subagent_type", "description", "prompt"]
  }
}
```

### 2.3 执行流程

```
主 agent 调用 task
  → 找到 SubagentSpec
  → 构造子 AgentLoop：
      - 独立 messages（只有子 agent 的 system prompt + 用户 prompt）
      - 受限 Registry（spec.tools 白名单）
      - 独立 ModelGateway（spec.model_purpose）
      - 独立预算上限（spec.max_turns，成本计入主会话）
  → 执行
  → 子 agent 结束 → 抽取结论
  → 作为 tool_result 返回主 agent（只返回结论，不返回全部中间过程）
```

**结论抽取**：子 agent 的最后一条 assistant 消息作为返回值。若子 agent 达到 `max_turns` 未完成，返回「已达上限，未完成」的提示。

**结果结构**

```json
{
  "status": "completed" | "max_turns" | "error",
  "summary": "子 agent 的结论文本",
  "findings": ["..."],
  "files_touched": ["..."],
  "cost": 0.03,
  "turns": 7
}
```

### 2.4 子 Agent 定义文件

`.coderagent/agents/<name>.md`：

```markdown
---
name: code-explorer
description: 在代码库中定位符号、追踪调用链、总结架构。只读，不修改文件。
tools: [read, grep, glob, ls]
model_purpose: cheap
max_turns: 15
---

你是一个代码库探索专家。给定一个目标（符号名、行为描述或问题），系统地定位相关代码：

1. 用 grep/glob 缩小范围
2. 用 read 阅读关键文件
3. 输出结论：涉及的文件与行号、调用关系、你的判断

不要修改任何文件。
```

**加载**：项目级 `.coderagent/agents/` + 用户级 `~/.coderagent/agents/`（用户级可覆盖同名）。

**内置子 agent**

| 名称 | 用途 | 工具 | 模型 |
|---|---|---|---|
| `code-explorer` | 定位/理解代码 | read grep glob ls | cheap |
| `verifier` | 独立验证（跑测试、复现 bug） | read bash | main |
| `refactorer` | 批量模式替换 | read edit grep glob | main |

---

## 3. F4.3 多模型路由

### 3.1 路由维度

| 维度 | 说明 |
|---|---|
| `purpose` | 固定用途映射（main / cheap / summarize / reflect）——M0 已预留 |
| `complexity` | 按任务规模自动选择（文件数、工具调用数、历史长度） |
| `budget` | 剩余成本不足时降档 |
| `user_override` | 用户在会话中显式指定（`/model`） |

### 3.2 策略

```python
# src/coderagent/models/router.py
@dataclass
class RoutingRule:
    when: str                      # 条件表达式，如 "tokens > 50000"
    purpose: str                   # 目标用途档位


class ModelRouter:
    def __init__(self, config: ModelConfig, gateway: ModelGateway): ...
    def resolve(self, purpose: str, context: dict) -> str:
        """返回实际使用的 model_name。"""
```

**默认策略**

```
主循环轮次 > 30 或 token > 50k  → 升级到高档模型
成本超预算 80%                   → 降档到廉价模型
压缩 / 经验沉淀 / 琐碎判断        → 廉价模型
```

### 3.3 UI 呈现

状态栏显示当前模型；切换模型时在消息流里插一条 `STATE_CHANGE` 事件，说明「因上下文变长，从 X 切换到 Y」。

---

## 4. F4.4 经验沉淀

### 4.1 目标

让 agent **跨会话记住**项目/用户层面的事实，例如「这个项目的测试用 `pytest -m slow`」「用户偏好中文注释」。

### 4.2 流程

```
会话结束（/clear 或退出）
  → 若本会话有值得沉淀的内容（改动了多个文件、踩了坑、确立了约定）
  → ModelGateway.complete(purpose="reflect", prompt=...)
  → 模型输出两类内容：
      {project_facts: [...], user_preferences: [...]}
  → 写入：
      .coderagent/memory/projects.md     （项目级）
      ~/.coderagent/CLAUDE.md             （用户级，需确认）
```

**写入护栏**

- 项目记忆**自动写**（内容是关于项目的客观事实）
- 用户记忆**必须用户确认**（UI 弹窗展示拟写入内容）
- 去重：写入前用模型判断是否与已有内容重复
- 长度上限：项目记忆文件 ≤ 200 行，超出时提示整理

### 4.3 读取

M2 已实现读取（项目/用户记忆作为指令块注入）。本节补充：记忆条目带 `source` 与 `created_at`，便于展示与淘汰。

---

## 5. F4.5 Skills 系统

Skill = 一个带说明、脚本与资源文件的可复用能力包。

```
.coderagent/skills/pdf-report/
├── SKILL.md          # front-matter(name, description) + 正文（使用说明）
├── scripts/
│   └── make_report.py
└── assets/
    └── template.docx
```

**与自定义命令的区别**

| | 自定义命令 | Skill |
|---|---|---|
| 触发 | 用户显式 `/name` | 模型按 `description` 自主决定调用 |
| 上下文 | 命令正文替换进 prompt | 正文作为「使用说明」注入，模型调用脚本执行 |
| 产物 | 对话消息 | 文件/脚本产物 |

**Skill 调用机制**：给模型注入一段技能清单（名称 + 描述 + 何时使用），模型决定加载某个 Skill 的完整说明 → 走 bash 执行其脚本。

**实现**：`extensions/skills.py` 扫描 skill 目录，解析 front-matter，构造技能索引注入 system prompt。

---

## 6. F4.6 插件机制

插件 = 第三方扩展包，提供新的工具、命令、hook、模型后端。

```python
# src/coderagent/extensions/plugins.py
class Plugin(Protocol):
    name: str
    def register(self, registry: "ExtensionRegistry") -> None: ...
```

**发现**

```
~/.coderagent/plugins/*/     （用户）
.coderagent/plugins/*/       （项目）
pip 安装的 entry point group "coderagent.plugins"
```

**扩展注册表**

```python
@dataclass
class ExtensionRegistry:
    tools: ToolRegistry
    commands: list[Command]
    hooks: HookConfig
    model_backends: dict[str, type]
```

**安全**：插件在主进程内执行（无沙箱），加载前打印清单并要求确认（首次加载时记录到信任列表）。

---

## 7. F4.7 远程沙箱

直接复用 `minisweagent.environments.extra` 下的实现：

| 环境 | 说明 |
|---|---|
| `swerex_docker` | SWE-ReX 管理的远程 Docker 容器 |
| `swerex_modal` | Modal 上的远程执行 |
| `contree` | 无 root 的受限容器 |

**接入方式**：`coderagent` 的 `Environment` 用 `minisweagent.environments.get_environment(config, default_type=...)`，配置里 `sandbox.type` 决定用哪个。

**远程沙箱的额外考量**

- 需要 checkpoint 的容器快照能力 → F4.1 的 `container_commit` 路径
- 延迟更高 → UI 需显示「远程执行中」状态而非本地 spinner
- 凭证：`SWE_REX_SERVER_URL` / `SWE_REX_API_KEY` 等走全局 `.env`

---

## 8. F4.8 可观测性

### 8.1 Trace 格式

与 mini 的 `trajectory_format: "mini-swe-agent-1.1"` 并列，新格式：

```json
{
  "trajectory_format": "coder-agent-1.0",
  "session": {...},
  "events": [...],
  "metrics": {
    "total_cost": 0.42,
    "total_tokens_in": 120433,
    "total_tokens_out": 8421,
    "per_tool": {"read": 42, "bash": 13, "edit": 5},
    "per_purpose_cost": {"main": 0.38, "summarize": 0.04},
    "duration_seconds": 412.3,
    "compactions": 3
  }
}
```

### 8.2 导出

```bash
coder export --session <id> --format json --out trace.json
coder export --session <id> --format otel --out trace.otlp
```

**OTel 导出**：把事件映射为 span（一次 turn = 一个 span，工具调用 = 子 span），便于用 Jaeger / Tempo 观察。

### 8.3 成本归因

按 `purpose` 与 `tool` 维度累计成本，回答「这次会话钱花在哪了」。

---

## 9. 任务分解

### T4.1 子 Agent 骨架
- [x] `SubagentSpec` + 定义文件加载
- [x] `task` 工具实现
- [x] 子 AgentLoop 构造（独立上下文、受限工具集、独立模型档位）
- [x] 结果结构化返回

### T4.2 内置子 Agent
- [x] `code-explorer` / `verifier` / `refactorer`
- [x] `/agents` 命令列出可用子 agent

### T4.3 模型路由
- [x] `RoutingRule` / `ModelRouter.resolve`
- [x] 默认策略（轮次/token/预算）
- [x] 状态栏与事件提示切换

### T4.4 经验沉淀
- [x] `reflect` prompt 与输出 schema
- [x] 项目记忆自动写入
- [x] 用户记忆需确认
- [x] 去重与长度上限

### T4.5 Skills
- [x] skill 目录扫描与 front-matter 解析
- [x] 技能索引注入 system prompt
- [x] 模型自主加载 skill 说明
- [x] `/skills` 命令

### T4.6 插件
- [x] `ExtensionRegistry` 与发现机制
- [x] 首次加载的信任确认
- [x] 插件 API 文档

### T4.7 远程沙箱
- [x] 配置 `sandbox.type` 接到 `minisweagent.environments`
- [x] 远程状态在 UI 的呈现
- [ ] 容器 checkpoint（可选，未实现）

### T4.8 可观测性
- [x] 指标累计
- [x] `coder export` 命令（json / otel）
- [x] 成本归因报表

---

## 10. 测试计划

| 文件 | 覆盖点 |
|---|---|
| `tools/test_task.py` | 子 agent 上下文隔离、工具白名单限制、成本计入主会话、max_turns 截断 |
| `models/test_router.py` | 路由规则求值、预算降档、上下文升级 |
| `extensions/test_memory.py` | 沉淀写入、去重、用户记忆需确认 |
| `extensions/test_skills.py` | skill 解析、索引注入 |
| `extensions/test_plugins.py` | 发现、信任确认、注册 |
| `test_export.py` | trace 格式、指标正确性 |

---

## 11. 风险

| 风险 | 对策 |
|---|---|
| 子 Agent 结果不可靠，主 agent 被误导 | 结果结构化返回（含 status）；主 agent 可要求重试；不自动采信未验证结论 |
| 子 Agent 成本失控 | 独立 `max_turns` + 独立成本上限；计入主会话总预算 |
| 经验沉淀写入错误信息污染长期上下文 | 用户记忆需确认；项目记忆带来源与时间；提供 `/memory` 查看与删除 |
| 插件在主进程执行有安全风险 | 首次加载需确认；插件目录不进版本库；文档明示信任模型 |
| 多模型引入行为不一致 | 路由切换在事件流中显式记录，便于回溯 |

---

## 12. Definition of Done

- [x] `task` 工具可委派子任务，主上下文不被污染
- [x] 子 Agent 工具白名单被强制执行
- [x] 模型路由能按上下文长度与预算自动升降档
- [x] 经验沉淀可写入项目记忆，用户记忆需确认
- [x] `coder export` 输出完整 trace 与指标

---

## 13. 实现说明（与原设计的偏差）

实现与原设计的差异如下，都是有意为之。

### 13.1 子 Agent

- 子 Agent 没有自己的 `AgentLoop`，而是由 `SubAgentRunner` 驱动一个循环：它有独立的
  messages、受限的 `ToolRegistry`、独立的 `ModelGateway` 和自己的 `max_turns`。另起一个
  `AgentLoop` 会带来第二套事件流和第二套会话状态，收益不大。
- 子 Agent 的成本加回主会话，主会话的预算因此仍然管得住它。计的是它自己那几次调用，
  详见 13.8。
- 内置子 Agent 放在 `core/subagent.py` 的 `BUILTIN_SUBAGENTS` 里，而不是单独的目录：
  它们是代码，不是配置。

### 13.2 模型路由

- 路由规则只比较数字。`tokens > 50000` 这样的写法有效，`state == done` 这样的写法永远
  不成立，不会被 `eval`，也不会报错。
- `ModelRouter` 有自己的 `main_model`。注入的模型（测试、脚本）不会被配置里的
  `model.model_name` 覆盖，路由因此不会把测试用的模型换掉。
- 默认策略是：预算用掉 80% 降档到廉价模型，轮次超过 30 或 token 超过 50k 升档到高档
  模型。升档只在配置了 `routing.strong` 时才发生。

### 13.3 经验沉淀

- 用户记忆的确认不是一个弹窗，而是写进 `.coderagent/memory/pending-memory.md`，用户用
  `/memory confirm` 确认、`/memory forget <text>` 删除。终端界面里做一个模态框，比一个
  文件复杂得多。
- 记忆条目没有 `source` 与 `created_at`：写入时去重，文件上限 200 行，超出的部分提示整理。

### 13.4 Skills

- 技能目录是 `.coderagent/skills/<name>/SKILL.md`，一个技能一个目录，因此技能可以带
  `scripts/` 与 `assets/`。
- 技能正文通过 `skill` 工具加载，工具的返回里还带着技能目录的路径，模型知道脚本在哪里。

### 13.5 插件

- 插件的信任不是弹窗，而是 `~/.coderagent/trusted-plugins.json` 里的一个列表，
  `/plugins trust <name>` 写入。第一次加载前问一次，问过就记住。
- 插件的形式是目录里的 `plugin.py`，里面有一个 `register(registry)` 函数，或者一个带
  `register` 方法的对象。pip 安装的插件走 `coderagent.plugins` 这个 entry point 组。
- 插件的命令注册到全局的 `COMMANDS` 里，所以插件的命令和内置的命令一样可用。

### 13.6 远程沙箱

- 只有 `bash` 工具的命令进沙箱。mini-swe-agent 的 `Environment` 协议只有 `execute`，
  没有文件操作，所以 `read`/`write`/`edit` 仍然作用于本机文件系统。
- 容器有自己的工作目录。本机会话的路径在容器里不存在，所以不传；要在容器里换目录，
  用 `sandbox.cwd`。
- 远程沙箱里的 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 魔法被关掉了：一轮对话由模型说
  结束，而不是由一个哨兵字符串结束。
- 容器 checkpoint 没有实现。它需要沙箱支持快照，而 mini 的环境没有这个接口。

### 13.7 可观测性

- `coder` 变成了一个命令组：主命令还是 `coder --task ...`，`coder export ...` 是它的
  子命令。`coder` 不带参数时仍然是终端界面。
- trace 从事件日志算出来，而不是另外记一份。日志是唯一的事实来源。
- 成本归因的维度是 purpose（`main`、子 agent 的档位）、model 和 tool。子 agent 的成本
  来自 `task` 工具返回的 JSON。
- token 数来自流式响应的 usage，之前的实现把它丢掉了。

### 13.8 成本核算（实测后修正）

真机联调时发现原来的成本算法是错的，这里是修正后的规则：

- 子 agent 的成本是它**自己**那几次调用的花费，不是它用的那个 gateway 的累计值。子 agent
  常常和主 agent 共用一个 gateway，累计值里混着主 agent 已经花掉的钱。
- 子 agent 用自己的模型时，它的花费记到主 gateway 上，所以主会话的预算仍然管得住它。
- 压缩时生成摘要的那次调用也是一次模型调用。它的花费写进 `compaction` 事件里，因此在
  事件日志里，和别的调用一样被计入。
- 一个会话的花费 = 事件日志里所有调用的花费之和。session、trace 指标、`/cost` 和
  `coder export` 报的是同一个数字。
- 子 agent 的 `files_touched` 只列**改过**的文件。读过的文件不算，读不是改。
