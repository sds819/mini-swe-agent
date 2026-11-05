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
- [ ] `SubagentSpec` + 定义文件加载
- [ ] `task` 工具实现
- [ ] 子 AgentLoop 构造（独立上下文、受限工具集、独立模型档位）
- [ ] 结果结构化返回

### T4.2 内置子 Agent
- [ ] `code-explorer` / `verifier` / `refactorer`
- [ ] `/agents` 命令列出可用子 agent

### T4.3 模型路由
- [ ] `RoutingRule` / `ModelRouter.resolve`
- [ ] 默认策略（轮次/token/预算）
- [ ] 状态栏与事件提示切换

### T4.4 经验沉淀
- [ ] `reflect` prompt 与输出 schema
- [ ] 项目记忆自动写入
- [ ] 用户记忆需确认
- [ ] 去重与长度上限

### T4.5 Skills
- [ ] skill 目录扫描与 front-matter 解析
- [ ] 技能索引注入 system prompt
- [ ] 模型自主加载 skill 说明
- [ ] `/skills` 命令

### T4.6 插件
- [ ] `ExtensionRegistry` 与发现机制
- [ ] 首次加载的信任确认
- [ ] 插件 API 文档

### T4.7 远程沙箱
- [ ] 配置 `sandbox.type` 接到 `minisweagent.environments`
- [ ] 远程状态在 UI 的呈现
- [ ] 容器 checkpoint（可选）

### T4.8 可观测性
- [ ] 指标累计
- [ ] `coder export` 命令（json / otel）
- [ ] 成本归因报表

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

- [ ] `task` 工具可委派子任务，主上下文不被污染
- [ ] 子 Agent 工具白名单被强制执行
- [ ] 模型路由能按上下文长度与预算自动升降档
- [ ] 经验沉淀可写入项目记忆，用户记忆需确认
- [ ] `coder export` 输出完整 trace 与指标
