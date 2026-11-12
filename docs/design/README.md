# Coding Agent 设计文档集

> 目标：在 mini-SWE-agent 的极简哲学之上，构建一个对标 Codex CLI / Claude Code 的交互式 coding agent。
> 状态：实现中（WIP）。M0 / M1 / M2 / M3 / M4 / M5 已完成。

## 里程碑进度

| 里程碑 | 主题 | 状态 | 代码位置 |
|---|---|---|---|
| M0 | 骨架与配置 | ✅ 已完成 | `src/coderagent/{core,config,models,run}` |
| M1 | 工具系统与权限 | ✅ 已完成 | `src/coderagent/{tools,testing}` |
| M2 | 上下文治理与会话管理 | ✅ 已完成 | `src/coderagent/core/{context,summarize,checkpoint,tokens,budget,history,instructions,memory}.py`、`src/coderagent/ui/commands/` |
| M3 | 交互体验与扩展 | ✅ 已完成 | `src/coderagent/ui/{tui.py,cli.py,commands/,widgets/}`、`src/coderagent/{extensions/hooks.py,tools/mcp.py}` |
| M4 | 进阶能力 | ✅ 已完成 | `src/coderagent/core/{subagent,sandbox,telemetry}.py`、`src/coderagent/extensions/{skills,plugins,reflect}.py`、`src/coderagent/models/router.py`、`src/coderagent/tools/builtin/{task,skill}.py` |
| M5 | Web 版 | ✅ 已完成 | `src/coderagent/web/` |

## 文档索引

| 文档 | 内容 |
|---|---|
| [coding-agent-architecture.md](coding-agent-architecture.md) | **主架构文档**：定位、能力差距矩阵、六层分层架构、模块设计、关键接口、配置、风险、依赖边界 |
| [coderagent-design-logic.md](coderagent-design-logic.md) | **设计逻辑文档**：为什么长成这样——三条承重决策、全局不变量、有意的不对称、逐层取舍、依赖地图 |
| [coderagent-questions.md](coderagent-questions.md) | **提问文档**：六组 33 问——上下文、工具、调度、memory/state、评测与观察、约束与恢复 |
| [coderagent-answers.md](coderagent-answers.md) | **答问录**：逐题作答，每条答案指向具体文件与函数，并说明取舍与已知瑕疵 |
| [coderagent-context.md](coderagent-context.md) | **专题：上下文管理与压缩**——怎么组上下文、怎么切、摘要怎么保证不丢东西 |
| [milestones/M0-skeleton.md](milestones/M0-skeleton.md) | M0 骨架与配置：Session / EventBus / Loop / Config 的逐条任务分解 |
| [milestones/M1-tools-permissions.md](milestones/M1-tools-permissions.md) | M1 工具系统与权限：ToolRegistry / PermissionPolicy / 内置工具规范 |
| [milestones/M2-context-session.md](milestones/M2-context-session.md) | M2 上下文治理与会话管理：结构化压缩 / 恢复 / 检查点 |
| [milestones/M3-ui-extensions.md](milestones/M3-ui-extensions.md) | M3 交互体验与扩展：TUI / MCP / Hooks / slash 命令 |
| [milestones/M4-advanced.md](milestones/M4-advanced.md) | M4 进阶能力：子 Agent / 模型路由 / 记忆 / 插件 / 可观测性 |
| [milestones/M5-web-interface.md](milestones/M5-web-interface.md) | M5 Web 版：FastAPI 应用 / SSE 事件流 / 审批 / 配置页 / 文件浏览 |
| [milestones/M5-web-modules.md](milestones/M5-web-modules.md) | M5 Web 版**模块与函数**设计：逐模块的接口签名 / 数据契约 / 不变量 |

## 一句话设计哲学

> 复用 mini-swe-agent 的**下半部分**（Model/Environment 协议、litellm 封装、YAML 配置、subprocess 沙箱原语），
> 重写它的**上半部分**（主循环、工具系统、上下文治理、权限层），再补上 Codex/Claude Code 的**扩展生态**（MCP / Hooks / Skills / Subagent）。

## 阅读顺序

1. 先读主架构文档的「能力差距分析」与「总体分层架构」两节，建立全局认知。
2. 再按 M0 → M5 顺序读里程碑文档，每个文档末尾都有该阶段的出口条件与 Definition of Done。
3. 实现时以里程碑文档里的任务清单（`- [ ]`）为 checklist。

## 快速索引：关键决策在哪里

| 决策 | 位置 |
|---|---|
| 六层分层架构与数据流 | 主架构 §3 |
| **为什么这么设计**（承重决策 / 不变量 / 取舍） | 设计逻辑 §2、§3、§5 |
| 事件日志是唯一事实来源 | 设计逻辑 §2.1 |
| 同步核心 + 界面订阅者 | 设计逻辑 §2.2 |
| 所有副作用过同一道闸 | 设计逻辑 §2.3 |
| fail-open 与 fail-closed 的分界 | 设计逻辑 §3.3 |
| 扩展是项目优先、规则是用户优先 | 设计逻辑 §4.1 |
| 改一处必须改另一处 | 设计逻辑 §9 |
| Session / EventBus 事件溯源 | 主架构 §4.1、M0 §2.2 |
| 结构化摘要 schema | 主架构 §4.4、M2 §2.3 |
| 权限模式与规则求值 | 主架构 §4.3、M1 §2.4 |
| 内置工具语义（尤其 `edit` 唯一匹配） | M1 §3 |
| 上下文超限兜底路径 | M2 §2.6 |
| MCP 客户端设计 | M3 §4 |
| Hooks 事件点与执行语义 | M3 §5 |
| Web 版为什么不改核心 | M5 §2、主架构 §4.6 |
| SSE 缓冲与 `seq` 空间 | M5 §3.2、M5-web-modules §5.1 |
| Web 版的路径安全三层 | M5 §9.1、M5-web-modules §10 |
| 权限的两个入口（设置页 / 聊天页） | M5 §8.5 |
| 跨里程碑接口契约 | 主架构 §9.3 |
| 与上游的依赖边界 | 主架构 §12 |
