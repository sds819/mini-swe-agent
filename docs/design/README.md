# Coding Agent 设计文档集

> 目标：在 mini-SWE-agent 的极简哲学之上，构建一个对标 Codex CLI / Claude Code 的交互式 coding agent。
> 状态：实现中（WIP）。M0 / M1 / M2 / M3 / M4 已完成。

## 里程碑进度

| 里程碑 | 主题 | 状态 | 代码位置 |
|---|---|---|---|
| M0 | 骨架与配置 | ✅ 已完成 | `src/coderagent/{core,config,models,run}` |
| M1 | 工具系统与权限 | ✅ 已完成 | `src/coderagent/{tools,testing}` |
| M2 | 上下文治理与会话管理 | ✅ 已完成 | `src/coderagent/core/{context,summarize,checkpoint,tokens,budget,history,instructions,memory}.py`、`src/coderagent/ui/commands/` |
| M3 | 交互体验与扩展 | ✅ 已完成 | `src/coderagent/ui/{tui.py,cli.py,commands/,widgets/}`、`src/coderagent/{extensions/hooks.py,tools/mcp.py}` |
| M4 | 进阶能力 | ✅ 已完成 | `src/coderagent/core/{subagent,sandbox,telemetry}.py`、`src/coderagent/extensions/{skills,plugins,reflect}.py`、`src/coderagent/models/router.py`、`src/coderagent/tools/builtin/{task,skill}.py` |
| M5 | Web 版 | 🚧 实现中 | `src/coderagent/web/` |

## 文档索引

| 文档 | 内容 |
|---|---|
| [coding-agent-architecture.md](coding-agent-architecture.md) | **主架构文档**：定位、能力差距矩阵、六层分层架构、模块设计、关键接口、配置、风险、依赖边界 |
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
2. 再按 M0 → M4 顺序读里程碑文档，每个文档末尾都有该阶段的出口条件与 Definition of Done。
3. 实现时以里程碑文档里的任务清单（`- [ ]`）为 checklist。

## 快速索引：关键决策在哪里

| 决策 | 位置 |
|---|---|
| 六层分层架构与数据流 | 主架构 §3 |
| Session / EventBus 事件溯源 | 主架构 §4.1、M0 §2.2 |
| 结构化摘要 schema | 主架构 §4.4、M2 §2.3 |
| 权限模式与规则求值 | 主架构 §4.3、M1 §2.4 |
| 内置工具语义（尤其 `edit` 唯一匹配） | M1 §3 |
| 上下文超限兜底路径 | M2 §2.6 |
| MCP 客户端设计 | M3 §4 |
| Hooks 事件点与执行语义 | M3 §5 |
| 跨里程碑接口契约 | 主架构 §9.3 |
| 与上游的依赖边界 | 主架构 §12 |
