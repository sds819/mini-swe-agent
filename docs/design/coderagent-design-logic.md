# coderagent 的设计逻辑

> 这份文档回答一个问题：**coderagent 为什么长成这样。**
>
> 主架构文档（[coding-agent-architecture.md](coding-agent-architecture.md)）回答的是「有哪些模块、
> 它们怎么分层、接口长什么样、每个里程碑做了什么」。那是 **what / how**。
> 这份文档回答的是 **why**：面对什么问题时，做了哪个选择，放弃了哪些备选，付了什么代价，
> 以及为什么这个选择会长成现在这个样子。
>
> 代码位置：`src/coderagent/`（84 个 Python 文件，11101 行）。文中每条结论都能在源码里找到出处，
> 引用格式是 `文件:行号`。

---

## 目录

1. [出发点：mini 的三条假设](#assumptions)
2. [承重决策](#load-bearing)
3. [贯穿全局的不变量](#invariants)
4. [有意的「不对称」](#asymmetry)
5. [逐层拆解：问题 → 决策 → 代价](#layer-by-layer)
6. [一轮对话的完整走查](#one-turn)
7. [扩展生态的信任模型](#trust)
8. [刻意不做的事](#not-doing)
9. [依赖地图：改 A 必须改 B](#dependency-map)
10. [这份逻辑的代价](#cost)

---

## 1. 出发点：mini 的三条假设 {#assumptions}

mini-SWE-agent 是**基准测试用的极简单轮 agent**。它的三条假设塑造了它的全部形态：

| 假设 | 表现 | 在 coderagent 里是否成立 |
|---|---|---|
| **线性历史** | `self.messages` 只是一个不断 `extend` 的列表（`src/minisweagent/agents/default.py:42`） | ❌ 打断 |
| **一次性** | `run()` 跑完就返回结果（`src/minisweagent/agents/default.py:88`） | ❌ 打断 |
| **只有 bash** | 唯一的工具是一个 `bash`（`src/minisweagent/models/utils/actions_toolcall.py`） | ❌ 打断 |

三条假设各对应一个真实需求：

- **线性历史 → 打断**：开发者的需求是「对话」，不是「跑批」。对话需要 **resume**（昨天关掉，
  今天接着聊）、**fork**（同一个任务两条路试试）、**压缩**（聊到第 80 轮上下文装不下）。
  这三件事都要求「状态可以被存取」，而线性列表本身没有存取的边界。
- **一次性 → 打断**：一次性意味着「跑完即弃」，也意味着**没有用户在场**。但 coding agent 的
  核心交互恰恰是**人在场**：它要改你的文件，可能改错，要问你。
- **只有 bash → 打断**：只有一个 bash 工具时，「读一个文件」和「删掉整个目录」在权限层
  看起来是同一类操作。但它们的风险差着几个数量级。**结构化工具不是为了方便，是为了
  让权限有分辨力。**

所以结论不是「给 mini 加功能」，而是：**复用 mini 的下半部分（模型/环境协议、litellm 封装、
YAML 配置、subprocess 沙箱原语），重写它的上半部分（主循环、工具系统、上下文治理、权限层）**。
这个取舍在 [coding-agent-architecture.md](coding-agent-architecture.md) §1 有完整表格。

下面三条承重决策（§2.1–2.3），就是重写出来的部分的骨架；
§2.4–2.6 讲工具调用链本身的三个决定。

---

## 2. 承重决策 {#load-bearing}

### 2.1 事件日志是唯一事实来源，其余全是推导出来的

**问题**：会话要能 resume、fork、回滚、要能审计「agent 到底干了什么」。如果状态散落在
`Session` 对象、`ContextEngine` 的 history、`Session.metadata`、还有各个计数器里，
「恢复一个会话」就变成「把所有字段都恢复一遍」，而漏掉一个字段就是静默的行为差异。

**决策**：**只有 JSONL 事件日志是事实来源**。`core/events.py` 的模块 docstring 就这么写
（`src/coderagent/core/events.py:1`）。会话状态是重放日志得到的：

- `SessionStore.rebuild()` 重放全部事件，重建 `state` / `turn_count` / `cwd` / `todos`
  （`src/coderagent/core/session.py:105`）。
- `ContextEngine.restore()` 重放日志，重建历史和摘要（`src/coderagent/core/context.py:87`）。
- `telemetry.collect()` 重放日志，算出成本和指标（`src/coderagent/core/telemetry.py:68`）。

**代价**：日志里同一条 TOOL_RESULT 会被写**两次**——`ToolExecutor._publish()` 写一次
（带 diff，`src/coderagent/tools/executor.py:181`），`ContextEngine._record()` 又写一次
（带 messages，`src/coderagent/core/context.py:123`）。看起来是冗余，其实是两种用途：
前者给 UI（要 diff），后者给重放（要 messages）。两个 payload 结构不同，不能合成一条。

**收益**：新增一个 UI（web 版就是这样加的）**不需要碰核心**；fork 就是复制事件文件
（`src/coderagent/core/session.py:150`）；崩溃恢复就是重放。

**边界**：`TEXT_DELTA` 和 `REASONING` **不进日志**（`src/coderagent/core/events.py:15-17`
有明确注释）。它们是瞬时的渲染数据，重放它们没有意义，而且一次回答能产生几百条，
会把日志撑爆。`Event.from_dict()` 对未知事件类型返回 `None` 而不是抛异常
（`src/coderagent/core/events.py:50`）——旧版本读到新版本写的日志不该崩。

### 2.2 核心是同步的，界面只是订阅者

**问题**：terminal、headless、web 三种界面，如果各写一套循环，就是三份会漂移的实现。

**决策**：`AgentLoop.run_turn()` 是**唯一**的执行路径（`src/coderagent/core/loop.py:139`），
它是同步函数。界面通过 `EventBus` 订阅事件（`src/coderagent/core/events.py:65`）。

TUI 和 web **都是 `EventBus` 的订阅者**，不是循环的拥有者。web 版额外起一个工作线程
（`src/coderagent/web/sessions.py:67` 附近的 `_worker`），但它调的还是同一个 `run_turn`。

**为什么是同步**：litellm 有同步 API，MCP 是 async SDK，textual 是 async。同步核心 +
各界面自己处理 async，是三种异步模型里最容易推理的一种。async 的 MCP 客户端用
「一个线程 + 一个 event loop」桥接（`src/coderagent/tools/mcp.py`），而不是把整个核
心 async 化。

**关键细节**：`_publish()` = 广播 + 写日志（持久），`_notify()` = 只广播（瞬时）
（`src/coderagent/core/loop.py:413` 和 `:409`）。所有需要重放的东西走 `_publish`，
流式增量走 `_notify`。这两个函数的区别，就是「2.1 那条决策」在代码里的落点。

**EventBus 是宽容的**：一个订阅者抛异常，只会被记日志，不会影响发布者
（`src/coderagent/core/events.py:74-79`）。渲染层的一个 bug 不应该让 agent 挂掉。

### 2.3 所有副作用过同一道闸

**问题**：agent 能做的事太多了——读、写、执行命令、装插件、调 MCP、跑子 agent。
如果每条路径各自实现权限检查，漏一条就是漏一个洞。

**决策**：**所有工具调用都过 `ToolExecutor._prepare()`**
（`src/coderagent/tools/executor.py:93`）。顺序是固定的：

```
hook(PreToolUse) → 权限求值 → ask/deny → 执行
```

而且**执行器是唯一的执行路径**——`AgentLoop` 只调 `executor.plan()` 和
`executor.execute()`（`src/coderagent/core/loop.py:224-226`），自己不碰工具。

**为什么 hook 在权限之前**：hook 可以改参数（`updated_input`），**被改写之后的那条命令**
才是被批准/被拒的那条。反过来就不成立了。

**兜底**：`plan()` 负责把模型的 tool_call 解析成动作，解析失败变成 `error` 字符串
（`src/coderagent/tools/executor.py:51`）。`_run()` 里的异常也变成 `Error: ...` 的
observation（`src/coderagent/tools/executor.py:160`）。**工具的错误不是异常，是给模型
看的一行文本**——这是整个 agent 与语言模型交互的基本语法。

**并行但有序**：多个 tool_call 可以并行执行，但结果**按原顺序**重排返回
（`src/coderagent/tools/executor.py:91`）。但只要这一批里有 `bash`/`write`/`edit`/
`multi_edit`（`SEQUENTIAL_TOOLS`，`src/coderagent/tools/executor.py:20`），整批就串行。
理由：写操作之间有顺序依赖，且 bash 的 cwd 语义在并发下会打架。

### 2.4 一次工具调用分两半：先记「想做什么」，再执行

**问题**：模型是概率的。它会调错工具名、调错参数、调不该调的工具。如果只在执行之后
才留痕，那么「模型本来想干什么」就永远查不到了——而这恰恰是排查 harness 问题时最想看的东西。

**决策**：把一次工具调用切成**执行之前**和**执行之后**两段，各记一次：

```
模型返回 tool_calls
   │
   ├─ plan()               规整参数：不是合法 JSON / 不是对象 → 记 error，不往下走
   │                       tools/executor.py:51
   │
   ├─ _publish(TOOL_CALL)  ← 执行之前。全部 action 和它们的参数
   │                       core/loop.py:225
   │
   ├─ _prepare()           查注册表 → PreToolUse hook → 权限 → 审批
   │                       tools/executor.py:93
   │
   ├─ _run()               on_path → before_write（checkpoint）→ 执行
   │                       tools/executor.py:149
   │
   └─ _publish(TOOL_RESULT) + observation（带 tool_call_id）
```

**为什么这么排**：

- `TOOL_CALL` 在执行之前 → 一次失败的调用，事后能看出它**本来**想改哪个文件。
  没有这条，一次 `Error: permission denied` 只说明「有个动作被拒了」，不说明「它想干什么」。
- `_prepare()` 在执行之前 → 被拒绝的工具**不会真的动过文件**。权限不是「执行时检查一下」，
  是「执行前就不让它发生」。
- observation 一定带 `tool_call_id`（`tools/executor.py:178`）→ 模型才能把结果对上号。
  少了它，模型看到的是一串没有来源的文本。

**代价**：日志里 TOOL_CALL 和 TOOL_RESULT 可能**不成对**——被拒的 action 只有前者。
这看起来像个 bug，其实是「拒了就是没发生」的如实记录。想统计成功率时要看 `TOOL_RESULT`，
想统计意图时要看 `TOOL_CALL`。

### 2.5 模型造工具、调错工具、参数不对：都有确定的落点

**问题**：模型偶尔会喊一个不存在的工具名，或者调一个不该调的工具。这是**必然**发生的，
不是 bug。问题只是：harness 拿它怎么办？

**决策**：三类错，三种落点，**没有一种会中断整轮**。

| 情形 | 落点 | 代码 |
|---|---|---|
| **造工具**（名字不在注册表里） | observation = `Error: unknown tool 'xxx'. Available tools: ...`，工具不执行 | `tools/executor.py:97` |
| **乱调**（调了不该调的） | 权限层判：模式 → 规则 → 越界检查 | `tools/permissions.py:137` |
| **参数不对** | 工具自己抛类型错误 → 兜成 `Error: ...` | `tools/builtin/fs.py:81`、`tools/executor.py:160` |

**为什么是「给模型一句话」而不是「报错」**：模型能读懂错误文本并自己改正；异常只会
把「一次回答里的一行字」升级成「进程崩溃」（§3.1）。

**为什么 `Available tools` 要列出来**：模型有时候只是**记错了名字**（把 `read` 写成
`read_file`）。给它一份清单，它下一轮就能对上。列表来自注册表，所以它永远和
「实际能调什么」一致——包括 MCP 工具和插件工具。

**为什么子 agent 也挡得住**：子 agent 的注册表是**白名单重建**的
（`SubagentRunner._restricted()`，`src/coderagent/core/subagent.py:195`），
白名单外的工具**根本不在表里**，所以不是「会被拒绝」，是「不存在」。

**边界（说清楚比藏着好）**：

1. **被裁掉的工具仍然能执行**。`registry.schemas()` 裁的是发给模型的 schema，
   注册表本身没动。模型如果还记得某个被裁掉的工具的名字，照样调得动——
   **裁剪省的是上下文，不是权限**。
2. **权限层判不了「合不合适」**。它判的是「这个工具在这个模式下、这条命令是否被允许」，
   不判「这个任务该不该用这个工具」。后者是模型的事。
3. **参数不做 schema 级校验**。schema 只是发给模型的说明；执行前不按它校验，
   靠工具自己的类型检查兜底。好处是**新增参数不用改校验器**，代价是错误信息
   来自工具而不是 schema。

### 2.6 「模型在乱调」要能被发现，所以留痕要早、要可数

**问题**：光有防护不够，还得能**发现**模型在乱调——否则 harness 退化了没人知道。

**决策**：三层可观测。

1. **事件层**：`TOOL_CALL`（执行前）+ `TOOL_RESULT`（执行后，含 diff）。
   前者给「意图」，后者给「事实」。
2. **指标层**：评测报告的 `tool_errors` 数的是 observation 里以 `Error:` 开头的条数
   （`eval/runner.py:353`）——**被权限拒绝的也算**，因为它们同样是模型在乱试的证据。
3. **判据层**：任务可以要求「必须用某个工具改某个文件」
   （`require_tools`，`{tools: [...], paths: [...]}`）。用 shell 绕过去不算完成——
   这样「`edit` 工具坏了」会**变成任务失败**，而不是被 agent 悄悄绕过去。
   反过来，`no-op` 任务测的是**不该改的时候别改**：乱改和不改是同一种 bug。

**为什么要有 `require_tools`**：只看任务结果是分辨不出「agent 干成了」和「agent
绕过去了」的。一个用 `bash` 重写文件、把检查跑绿的任务，看起来是成功的，
但 `edit` 工具已经坏了没人知道。

---

## 3. 贯穿全局的不变量 {#invariants}

下面这几条在代码里到处出现，它们是「一致性规则」，不是某个模块的局部实现。

### 3.1 失败是数据，不是异常

工具失败 → observation 里的一行 `Error: ...`；hook 失败 → 忽略或按 `strict` 决定；
MCP 断了 → 重连一次；模型返回格式不对 → 归一化后继续。

只有**编程错误**（配置里的非法值、类型不对）才真的抛异常。理由很实际：
模型和用户输入是不可靠的，用异常处理它们会把「一次回答里的一行字」升级成
「进程崩溃」。

### 3.2 显式优于隐式

- 成本只有一个定义：**事件日志里所有模型调用之和**。`session.total_cost` 是
  `collect(events).total_cost`（`src/coderagent/core/session.py:130`），
  不是某个计数器累加出来的。子 agent 的成本会**记回主 gateway**
  （`src/coderagent/core/subagent.py:220`），压缩摘要如果用了另一个模型也会记回主 gateway
  （`src/coderagent/core/context.py:225`）。所以 `/cost`、`coder export`、session 总额
  报的是同一个数。
- 模式（mode）是**共享的可变对象**。`web` 的 `set_mode()` 直接改
  `loop.executor.policy.mode`（`src/coderagent/web/sessions.py:271`），**立刻生效**，
  不需要重建会话。因为执行器问的就是这个对象。
- 同时，`_mode_text()` **每次组上下文都重新读**权限模式（`src/coderagent/core/context.py:162`），
  所以模型每轮都被告知当前模式。模式不是写死在 system prompt 里的。

### 3.3 fail-open 与 fail-closed 的分界

这不是「一边倒」的哲学，而是**按后果分类**：

| 场景 | 策略 | 理由 |
|---|---|---|
| Hook 崩溃 / 超时 / 返回非 JSON | **fail-open**（放行） | hook 是增强，不是闸门。它挂了不该拦住正常工作 |
| Hook 明确返回 deny | **fail-closed**（拦截） | 明确的拒绝不能被忽略 |
| Hook 非零退出码 | 只在 `strict: true` 时拒绝 | 默认不信任退出码，只信任 JSON 里的 `decision` |
| 路径越界 | **fail-closed** | `within_bounds()` **不能被 `allow` 规则放宽**（`src/coderagent/tools/permissions.py:223`） |
| 没有人能审批（headless） | **fail-closed** | `HeadlessApprover` 直接 DENY，并把原因回传给模型（`src/coderagent/tools/permissions.py:80`） |

`within_bounds()` 那条特别值得强调：一条 `allow` 规则**能**让模型读工作目录外的文件，
那等于把整块磁盘交给一个浏览器能驱动的 agent。权限规则的匹配和路径边界检查是
**两道独立的闸**，后者不接受前者的放行。

### 3.4 一次会话 = 一条写入路径

`SessionStore.append()` **没有锁**（`src/coderagent/core/session.py:81`）。这是有意的：
一个会话同一时刻只有一个 worker 线程在写。web 里如果上一轮还没跑完就再发消息，
`submit()` 抛 `SessionBusy`（`src/coderagent/web/sessions.py:129`），API 把它变成
**409**（`src/coderagent/web/api.py:219`）。

加锁会掩盖「两个写入者」的逻辑错误；让它显式失败，反而逼着上层把并发语义说清楚。

---

## 4. 有意的「不对称」 {#asymmetry}

下面这几处**看起来像 bug，其实是刻意的**。如果不写下来，下一个维护者很可能会「修」它。

### 4.1 扩展是项目优先，规则是用户优先

| 东西 | 谁赢 | 代码 |
|---|---|---|
| 技能（skills） | **项目**赢 | `src/coderagent/extensions/skills.py:78` |
| 子 agent | **项目**赢 | `src/coderagent/core/subagent.py:90` |
| 插件 | **项目**赢 | `src/coderagent/extensions/plugins.py:134` |
| 权限规则 | **用户**赢 | `src/coderagent/tools/rules.py:93` |

原因不同：技能/子 agent/插件是**这个项目的工作方式**，项目当然覆盖通用的；
但权限规则是**用户的安全边界**——用户在 `~/.coderagent/rules.yaml` 里写的
「不许动这些路径」，不该被仓库里的一份配置覆盖掉。仓库可能是别人 clone 下来的。

指令文件也是用户优先：`~/.coderagent/CLAUDE.md` 在前，项目 `AGENTS.md`/`CLAUDE.md` 在后
（`src/coderagent/core/instructions.py:35`）。

### 4.2 `within_bounds()` 不接受 `allow` 规则

见 §3.3。这是**故意的**——注释里直说了
（`src/coderagent/tools/permissions.py:223`）。代码上表现为**边界检查在规则之后**
（`src/coderagent/tools/permissions.py:147-151`）：

```python
if tool in PATH_TOOLS:
    path = str(params.get("path", ""))
    if path and not self.within_bounds(path):
        """A rule cannot open the disk: the bounds hold in every mode."""
        return Decision("deny", matched, self._outside_reason(path))
```

规则先把 `decision` 算出来，但**边界检查在它之后**——匹配到 `allow` 规则也绕不过去，
越界的路径一律返回 `deny`。

### 4.3 同一个 TOOL_RESULT 写两次

见 §2.1。两份 payload 结构不同：一份带 `diff`（给 UI），一份带 `messages`（给重放）。

### 4.4 工具 schema 按预算裁剪，而且 `bash`/`read` 永不裁

`registry.schemas(budget_tokens)` 按 `TRIM_ORDER` 从低频工具开始丢
（`src/coderagent/tools/registry.py:55`），但 `bash` 和 `read` 在 `NEVER_TRIM` 里
（`src/coderagent/tools/registry.py:26`）。

理由很实在：上下文快满了的时候，agent 最需要的恰恰是「再读一个文件」和「跑一条命令」，
而不是 `bash_output` 或 `skill`。裁剪顺序反映的是**应急时的可用性**，不是重要性排序。

### 4.5 流式增量不进缓冲

web 的环形缓冲只保留非瞬时条目（`src/coderagent/web/sessions.py:99`，
`TRANSIENT_KINDS` 在 `src/coderagent/web/events.py`）。一次回答能产生几百条
`text_delta`，进了缓冲就能把会话历史挤出去。整段答案随后以一条
`assistant_message` 进缓冲。

代价是：晚连上的浏览器**看不到**逐字的流式过程，但能看到完整答案。

### 4.6 TOOL_CALL 和 TOOL_RESULT 不成对

被权限拒绝的 action **只有** `TOOL_CALL`，没有 `TOOL_RESULT`——因为它确实没执行。

这看起来像日志丢了东西，其实是「拒了就是没发生」的如实记录（§2.4）。
代价是：**统计调用成功率不能直接数事件对**，得看 observation；
**统计模型意图要数 `TOOL_CALL`**。

### 4.7 工具被裁掉了，但没被禁用

`registry.schemas(budget_tokens)` 裁的是发给模型的 schema，注册表本身没动。
所以一个被裁掉的工具**仍然能执行**——模型如果还记得它的名字。

这是刻意的：**裁剪解决的是「上下文放不下」，不是「这个工具不该用」**。
真要禁用一个工具，用 `tools.disabled`（黑名单）或权限规则。
把两件事混在一起，会出现「模型看不见 schema 却调得动」这种更难解释的状态。

---

## 5. 逐层拆解：问题 → 决策 → 代价 {#layer-by-layer}

### L0 会话内核

**问题**：会话要能存、能取、能分叉、能回滚，还要能被审计。

**决策**：事件溯源（§2.1）。`SessionStore` 只管 append 和 replay，不负责业务语义。

**代价**：同一条事件写两遍（§4.3）；重放的代码路径要和写入路径保持一致，
多了一处容易出错的地方。

### L1 环境层

**问题**：命令要在哪跑？要不要容器？

**决策**：环境是可插拔的（`build_environment()`，`src/coderagent/core/sandbox.py:26`，
在 `src/coderagent/run.py:143` 被调用），
复用 mini 的 `minisweagent.environments.get_environment`，支持 local / docker /
singularity / swerex_docker / swerex_modal / bubblewrap / contree 七种。

**代价**：本地模式下没有隔离，安全性完全依赖权限层。所以权限层才必须是**唯一**
的执行路径（§2.3）——不能有绕过它去跑命令的地方。

### L2 工具层

**问题**：13 个内置工具（11 个基础工具 + `task` + `skill`），每个工具的风险不一样，
怎么统一管？

**决策**：工具本身**只管做事**，不做权限判断。所有权限集中在
`PermissionPolicy.evaluate()`（`src/coderagent/tools/permissions.py:137`），
所有 hook 集中在执行器的前后。

**求值逻辑**：按顺序遍历规则，**后写的赢**（所以用户规则后加载 → 用户赢）。
三种模式的选择语义在 `_default_decision()`：read 类工具在所有模式下都 allow，
plan/readonly 模式下写工具 deny，acceptEdits 模式下写工具 allow 而 bash 仍 ask。

**匹配方式不一样**：路径类工具用 **glob**（`glob_to_regex`，`*` 不跨 `/`，`**` 跨，
`src/coderagent/tools/permissions.py:90`），bash 用 **正则**（且必须对上每一段的**开头**——
`git push` 能对上 `git push origin main`，对不上 `echo "git push"`）。
因为「允许 `src/**/*.py`」和「允许 `npm test`」是两种形状。

**代价**：模式本身就是一个小语言，需要文档，也会有边界情况
（正则写错会被静默当作不匹配，`src/coderagent/tools/permissions.py:265-266` 的
`except re.error: return False`）。

**工具层拦得住「乱调」，拦不住「调错」**：权限层能判「这个工具在这个模式下允不允许」，
但判不了「这个任务该不该用这个工具」——那是模型的判断。参数对不对也不归权限层，
归工具自己（§2.5）。

**执行器只回答两个问题**：这个工具存在吗？允许它跑吗？**「模型是不是想干这件事」不在职责范围内**。

### L3 上下文引擎

**问题**：上下文是有限的，但对话是无界的。

**决策**：**组装的顺序固定**（`build_messages()`，
`src/coderagent/core/context.py:145`）：

```
system → 权限模式说明 → 指令+记忆+todos → 摘要 → 历史
```

每一段的来源单一，改一处不会漏掉另一处。

**压缩产出结构化摘要**，不是自由文本（`FIELDS`，
`src/coderagent/core/summarize.py:14`）：

```
goal / findings / decisions / files_touched / open_questions / next_steps / errors_seen
```

**为什么结构化**：自由文本摘要会丢掉「改了哪些文件」「还剩什么问题」。
结构化字段让压缩后的会话**仍然可查询**。而且 `files_touched` 有一个专门的校验：
如果摘要说没碰过文件，但历史里明明有写操作，就判定摘要失败，改用
`conservative_summary()`（判定在 `src/coderagent/core/context.py:284-306` 的 `_summarize()`，
兜底摘要本身在 `src/coderagent/core/summarize.py:257`）。

**切点在轮边界**（`_cut_index()`，`src/coderagent/core/context.py:252`）：
两个规则取大者——保留最近 N 轮，或保留上下文窗口的 X% 的 token。
「取大者」是为了兼顾「很多小轮」和「几个大轮」两种情况。

**代价**：每次组上下文都要重算 token 估算，有点浪费；换来的是**摘要和历史不冲突**
（摘要永远只有一份，新的摘要输入里带上旧的）。

### L4 模型网关

**问题**：可能要换模型（路由），可能要换后端（litellm / 自定义），要算钱。

**决策**：网关在后端之上包一层，负责记账和模型切换。路由规则是**解析出来的**，
不 `eval`——配置文件跑不了代码（`src/coderagent/models/router.py:78`）。

**模型切换的一个坑**：路由每轮可能重建 backend，所以比较时必须比**解析后的真名**
而不是别名，否则永远不相等 → 每轮换一次 backend（这个问题真实踩过）。
现在 `loop._route()` 先 `backend_for(name)` 再比 `backend.model_name`
（`src/coderagent/core/loop.py:321`）。

**上下文溢出的兜底**：provider 报 context 超长 → `force_compact()` → 重试一次
（`src/coderagent/core/loop.py:381` 的 `_query`）。判定靠异常类型 + 文本标记
双保险（`src/coderagent/models/gateway.py:12`）。

### L5 界面层

**问题**：三套界面，共享同一套命令和审批。

**决策**：slash 命令的核心**零 textual 依赖**——处理器只通过 `context.say(...)` 说话
（`src/coderagent/ui/commands/builtin.py`）。所以 TUI、CLI、web 都能直接复用。
每个界面往 `CommandContext` 里注入自己的钩子，比如 `quit`
（`src/coderagent/ui/commands/__init__.py`）：TUI 传 `action_quit`，headless 传
空操作，web **不传** → 浏览器里 `/exit` 会说「服务还在跑，去启动它的终端按 ctrl+c」。

**审批**：TUI 里 `y/n/a` 是带编号的方框，能用方向键选（`src/coderagent/ui/widgets/approval_prompt.py`）。
web 里是 HTTP 请求 + SSE 推送。headless 里没有审批人 → `HeadlessApprover` 直接拒。

**web 的额外设计**：SSE 而不是 WebSocket（单向推送，自带重连）；
写接口要 `X-Coder-Client: 1` 头（`src/coderagent/web/api.py:49`，
跨站浏览器发不出这个头）；**没有认证**（单用户本机工具，加 token 反而挡了脚本化调用，
这是明写在决策表里的取舍）；`/items` 和 `/stream` 共用一个 `seq` 空间
（`src/coderagent/web/sessions.py:64`），所以客户端可以用一个整数表达「我看到哪儿了」。

### L6 扩展层

见 §7。

---

## 6. 一轮对话的完整走查 {#one-turn}

从用户敲下一句话，到答案出现在屏幕上，路径是这样的（括号里是文件）：

```
用户输入
  │
  ├─ hook(UserPromptSubmit) 可能改写 prompt        core/loop.py:145
  │    原文被记在 payload["original"] 里，不丢
  │
  ├─ context.append(user message) → 写日志           core/context.py:107
  │
  └─ while True:                                    core/loop.py:176
       │
       ├─ maybe_compact()   上下文快满了就压          core/loop.py:191
       ├─ _route()          这轮用哪个模型            core/loop.py:192
       ├─ _query()          调模型，超限就压缩重试    core/loop.py:193
       │
       ├─ 有 tool_calls？
       │    ├─ executor.plan()      解析成动作        tools/executor.py:51
       │    ├─ _publish(TOOL_CALL)   写日志（在执行之前）core/loop.py:225
       │    ├─ executor.execute()   → _prepare()      tools/executor.py:93
       │    │      查表 → hook → 权限 → ask/deny → 跑
       │    │        拒绝不是异常，是一行 Error:
       │    └─ _publish(TOOL_RESULT) 写日志（带 diff）
       │
       ├─ 没 tool_calls？
       │    └─ Stop hook 可以拦一次（最多 3 次）       core/loop.py:208
       │
       └─ 循环条件：取消 / max_turns / cost_limit
```

有几个地方值得停下来看：

- **循环条件的检查在每一轮的开头**，不在末尾。所以「取消」最多延迟一轮。
- **成本检查用的是 `session.total_cost`，不是本轮的花费**（`core/loop.py:185`）。
  子 agent 花的钱也算在这个会话头上——用户看到的「这次会话花了多少」是完整的。
- **Stop hook 最多拦 3 次**。拦多了模型会陷入「解释为什么该停」的循环。
- **审批的等待是在执行器里同步阻塞的**。TUI 是异步的，所以 `TUIAprover` 用
  `asyncio` 把请求转回主循环；web 是把请求放进队列、用 SSE 回推结果。

---

## 7. 扩展生态的信任模型 {#trust}

扩展方式，**信任等级完全不同**。这不是疏忽，是刻意的分层：

| 扩展 | 执行位置 | 信任模型 |
|---|---|---|
| **Hook** | 子进程 | 最不可信也最安全：进程隔离，JSON 进 JSON 出，超时就放弃（fail-open） |
| **Skill** | 不执行 | 只是 markdown，进 prompt，靠模型自觉 |
| **MCP** | 外部进程/服务 | 独立进程，工具名带 `mcp__server__tool` 前缀，仍过权限层 |
| **Plugin** | **主进程内** | 最危险：没有沙箱，所以要进信任表 `~/.coderagent/trusted-plugins.json` |
| **子 agent** | **主进程内** | 同插件，但工具被白名单限制（`SubagentRunner._restricted()`，`src/coderagent/core/subagent.py:195`），且共享同一份权限模式 |

插件没有沙箱这件事是明说的（`src/coderagent/extensions/plugins.py:13`）。
所以有信任表，`/plugins trust` 才能加载。

**MCP 的两个具体决定**：

- 工具名统一加 `mcp__<server>__<tool>` 前缀，避免和内置工具撞名，也和 Claude Code 生态兼容。
- MCP 是 async SDK，agent 是同步的 → **每个 server 一个线程 + 自己的 event loop**
  （`src/coderagent/tools/mcp.py`）。断线自动重连一次。

**MCP 工具照样过权限层**（默认 `ask`）。这是重要的：接进来的 server 是用户自己选的，
但它的工具照样可能删文件。

---

## 8. 刻意不做的事 {#not-doing}

写下来是为了防止「以后有人顺手加上」：

- **不给 Web 版加认证**。单用户本机工具，信任模型同 `coder` 命令行。加 token 会挡住
  脚本化调用。（决策表第 19 条）
- **不用 WebSocket**。单向推送，SSE 自带重连和心跳，少一个协议少一份状态。
- **不把流式增量写进日志 / 缓冲**。见 §4.5。
- **不 `eval` 路由规则**。配置里的规则是数据，不是代码。
- **不在插件里做沙箱**。做不到，就明确要求信任。
- **不把 mini 的 `DefaultAgent` 改造成多轮**。它的线性历史假设是硬约束，改造等于重写。
- **不给 `within_bounds()` 留后门**。见 §4.2。
- **不用「异常」表达工具失败**。见 §3.1。
- **不按 schema 校验参数**。schema 只是发给模型的说明；校验靠工具自己的类型检查。
  好处是新增参数不用改校验器，代价是错误信息不统一。
- **不因为 schema 被裁就禁用工具**。见 §4.7。
- **不让权限层判断「合不合适」**。它只判「允不允许」——合不合适是模型的事。
  越界的部分由 `within_bounds()` 单独兜（§4.2）。

---

## 9. 依赖地图：改 A 必须改 B {#dependency-map}

这张表是本文档最实用的部分。

| 改了 | 必须同时改 |
|---|---|
| 新增 `EventType` | `web/events.py` 的 `normalize()`（否则 web 看不到这个事件）；如果它进日志，还要看 `ContextEngine.restore()` 能不能重放它 |
| 改了 TOOL_RESULT 的 payload 结构 | `ContextEngine.restore()`（重放）、`ContextEngine._record()`（写入）、`ToolExecutor._publish()`（写入）、`web/events.py`（展示） |
| 改了权限模式 | `PermissionMode` 枚举、`_default_decision()`、`mode_block()`（模型要知道）、`MODE_NOTES`、web 的模式选择器、文档 |
| 改了规则匹配方式 | `glob_to_regex()`、`_matches()`、`pattern_for()`（`always` 要写回规则文件）、`tools/rules.py` 的序列化 |
| 新增一个内置工具 | `ToolRegistry` 的默认列表、`README`/`docs/usage` 里的工具表、可能还要进 `SEQUENTIAL_TOOLS` |
| 改了工具错误的文本形状 | `executor.py` 里所有 `Error: ...` 前缀、`summarize.py` 的 `recent_errors`（靠 `Error:` 前缀识别）、`eval/runner.py` 的 `_tool_errors()`、工具层文档 |
| 新增一个内置 slash 命令 | `ui/commands/builtin.py`、**两份** `docs/usage/coderagent_commands{,_zh}.md` 的表格、`docs/usage/coderagent_features{,_zh}.md` 里的**数量**（24→25 这种）、`docs/design/milestones/M5-web-interface.md` 里的数量 |
| 改了成本口径 | `AgentLoop._bill()`、`ModelGateway` 的记账、`SubAgentRunner._result()`（记回主 gateway）、`ContextEngine.compact()`（摘要模型的花费）、`telemetry.collect()`、`/cost` 命令、`coder export` |
| 改了上下文的组装顺序 | `ContextEngine.build_messages()`、`_mode_text()`、`_instruction_text()`、`_summary_text()`、`estimated_tokens()`（预算检查依赖它） |
| 加了新的扩展类型 | `run.py` 的 `build_loop()`（装配）、信任模型（放进哪一档）、`/plugins` `/mcp` `/hooks` `/skills` 命令的输出 |
| 改了 `CommandContext` 的字段 | 三个界面（`ui/tui.py`、`ui/cli.py`、`web/sessions.py`）都要构造它 |

**特别提醒**：改内置命令/工具的数量时，**文档里的数字要一起改**。这个坑踩过——
`/exit` 加进去之后，`coderagent_features{,_zh}.md` 的「24 个」和
`M5-web-interface.md` 的「23 个」全变成了错的。

---

## 10. 这份逻辑的代价 {#cost}

诚实地列一下这套设计换来了什么、付出了什么：

| 代价 | 换来了 |
|---|---|
| 同一条事件写两遍 | UI 和重放各自拿到需要的形状 |
| 重放逻辑必须和写入逻辑一致 | 崩溃恢复、fork、审计、指标全都免费 |
| 规则模式是一种小语言 | 三态决策（allow/ask/deny）+ 能解释「为什么被拦」 |
| 权限检查只能有一个入口 | 新增执行路径（子 agent、MCP、插件）不会漏检 |
| 事件日志会变长 | 完整审计能力 |
| 摘要压缩有信息损失 | 换来的上下文空间；用结构化字段把损失压到最小 |
| 没有认证 | 零配置的本机工具体验 |
| 日志里 TOOL_CALL 和 TOOL_RESULT 不成对 | 被拒的动作**确实没发生**，如实记录；意图和事实分开看 |
| 模型调错工具只能靠它自己改 | 执行器不猜模型的心意；错误文本 + 可用工具清单是它能拿到的全部信息 |

### 一句话总结

coderagent 的设计逻辑可以压成一句：

> **把「发生了什么」和「怎么做的」分开——前者记在事件日志里，后者由一个同步核心 +
> 三个订阅者共享；而所有会碰到用户世界的东西，必须从同一个闸门过去。**

其余的（13 个工具、25 个命令、5 类扩展机制、3 套界面）都是这条主线的展开。

---

## 相关文档

| 文档 | 内容 |
|---|---|
| [coding-agent-architecture.md](coding-agent-architecture.md) | 主架构：分层、模块、接口、19 条关键决策 |
| [coderagent-answers.md](coderagent-answers.md) | 逐题作答：现在长什么样（本文讲「为什么长成这样」） |
| [coderagent-context.md](coderagent-context.md) | 专题：上下文管理与压缩 |
| [README.md](README.md) | 文档索引与阅读顺序 |
| [milestones/M0-skeleton.md](milestones/M0-skeleton.md) … [M5-web-modules.md](milestones/M5-web-modules.md) | 各里程碑的任务分解与验收 |
