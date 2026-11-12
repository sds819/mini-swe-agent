# Coding Agent 答问录

> 这份文档回答 [coderagent-questions.md](coderagent-questions.md) 里的 41 个问题。
> 每条答案的格式是：**结论** → **它落在哪** → **为什么这么定**（取舍）。
> 代码位置全部相对 `src/coderagent/`，测试相对 `tests/coderagent/`。
>
> 读法建议：先看每节的「一句话」，需要动手时再顺着文件路径跳。设计层面的「为什么」见
> [coderagent-design-logic.md](coderagent-design-logic.md)，本文只讲「现在长什么样」。

---

## a. 上下文是如何管理的

> 本节是浓缩版，展开见专题 [coderagent-context.md](coderagent-context.md)（含完整的保真机制清单）。

### a1 一次请求发给模型的消息由哪几部分组成？

**结论**：固定五段、顺序不可换，由 `core/context.py` 的 `ContextEngine.build_messages()` 组装。

1. **system prompt** —— `system` 角色，来自 `agent.system_prompt`；
2. **权限模式说明** —— `user` 角色，`<permission_mode mode="plan">…</permission_mode>`；
3. **指令 + 记忆 + todo** —— 合并成**一条** `user` 消息（`ContextEngine._instruction_text()`）；
4. **压缩出来的摘要** —— `user` 角色，`<session_summary>…</session_summary>`；
5. **历史消息** —— 原始的 assistant / user / tool 消息列表。

**为什么**：摘要在历史之前，因为被摘要的是**更早**的那部分；指令和 todo 合成一条，是因为它们性质相同（都是「本轮的外部状态」），拆成多条 user 消息会让模型误以为用户说了好几句话。历史放在最后，因为它是「刚刚发生的事」。

**取舍**：第 2 段和第 4 段是两条相邻的 `user` 消息，中间没有 assistant。这在 provider 侧合法，但严格说不是一段自然对话——见「已知瑕疵」一节。

### a2 上下文预算怎么算？token 怎么估？

**结论**：`core/budget.py` + `core/tokens.py`。

- **窗口大小**：`context_window_for(model_name)` 按模型名前缀查表（`gpt-` 128k、`claude` 200k、`deepseek` 64k、`gemini` 1M、`minimax` 204800……）。**只有用户没显式配 `context.context_window` 时才生效**——`run.py` 的 `_context_config()` 会检查 `"context_window" in config.context.model_fields_set`。显式配置永远赢。
- **可用上限**：`BudgetGuard.limit() = max(0, context_window - reserved_output)`，`reserved_output` 默认 8000。
- **压缩阈值**：`should_compact(estimated) = estimated > min(int(context_window * compact_threshold), limit())`，默认 `compact_threshold=0.8`。两个阈值取小的那个，即**比例阈值和绝对上限谁更紧听谁的**。
- **token 估算**：装了 `tiktoken` 就用 `cl100k_base` 精确算（含 tool schema 的 JSON 长度，每条消息额外 4 token 开销）；没装就退回启发式：`字符数 / 3.6 + 4 × 消息数`。

**为什么**：估算只是用来**决定要不要压缩**，不用来精确计费，所以宁可便宜。但 tiktoken 存在时用精确值，能少很多次无谓压缩。

**取舍**：启发式常数（3.6）是拍出来的经验值，对中文偏保守（中文一个字约 1–2 token）。

### a3 什么时候触发压缩？切点怎么选？

**结论**：`ContextEngine.maybe_compact()`，每轮问模型之前调一次（`core/loop.py` 里在 `_query()` 前）。

**三个触发条件**（任一成立就压）：

1. `config.context.auto_compact` 为真，且估算 token 超过预算阈值；
2. 距上次压缩超过 `compact_every_turns`（默认 40）轮；
3. provider 报上下文溢出 → `force_compact()` 强制压一次再重试。

**切点**在 `ContextEngine._cut_index()`：

- 候选切点只有**轮边界**（`History.turn_starts()`，即每条 role 为 user 的消息）。切在轮边界上，工具结果消息才不会跟「发起它的那条 assistant 消息」分家。
- 两个条件**取更严的**：一是「保留最近 `keep_recent_turns`（默认 20）轮」，二是「保留最近 `keep_recent_token_ratio`（默认 0.4）个窗口的 token」——哪个切得更靠前就切哪里。
- 还有一条**硬上限**兜底：切完之后剩余部分 + 摘要的 token 也不能超过 `guard.limit()`，超了就继续往后切一个轮。

**为什么**：宁可多留一点，也不要让切点落在半个工具调用中间——那会让模型看到「结果没了，但请求还在」。

### a4 被切掉的内容去哪了？摘要失败怎么办？

**结论**：`core/summarize.py` + `ContextEngine.compact()`。

- **摘要 schema**（`Summary` / `FIELDS`）：`goal`、`findings`、`decisions`、`files_touched`、`open_questions`、`next_steps`、`errors_seen`，再加一个**派生**字段 `recent_errors`（从消息里直接算，不问模型）。`files_touched` 的每一项是 `{path, change, state}`。
- **永远只有一份摘要**：`self.summaries = [summary]` 是**替换**不是追加。所以第二次压缩时，**上一份摘要会作为额外输入喂给模型**——否则摘要会越堆越多把预算吃光。
- **失败判定**：解析不出 JSON → 失败；**压缩掉的段落里有写操作、但摘要里 `files_touched` 是空的** → 也算失败（模型忘了改过文件，说明它没读懂）。失败就**重试一次**。
- **两次都失败** → `conservative_summary()` 兜底：`goal` 写「对话前半部分被压缩了」，`findings` 放最后 5 条消息（每条截 400 字），`next_steps` 写「重新读一遍提到的文件来恢复细节」。
- **落地**：写一条 `EventType.COMPACTION` 事件（`compacted_messages` / `tokens` / `summary_tokens` / `summary_ratio` / `cost` / `summary`），历史被截断成 `history.messages[cut:]`。
- **历史装不下一个提示词时**：按 map-reduce 做——`chunk_messages()` 按轮切块，每块摘要一次，再用 `merge_prompt()` 把若干 partial 合成一份（带上一份摘要）；合并失败时用纯代码的 `merge_summaries()` 拼起来，一条不丢。

**为什么**：摘要失败不能变成「静默丢历史」。兜底摘要很笨，但它诚实地告诉模型「你丢了东西，去重读」。

### a5 指令文件从哪儿加载？优先级？子目录怎么办？

**结论**：`core/instructions.py`。

- `load_instructions(cwd, user_home)` 按顺序加载：用户 `CLAUDE.md` → 项目 `AGENTS.md` → 项目 `CLAUDE.md`。渲染成 `<project_instructions source="AGENTS.md">…</project_instructions>` 块。
- **子目录惰性加载**：`subdirectory_instructions(path, cwd)` 从 `cwd` 往 `path` 逐层走，**由深到浅**加载每层的 `AGENTS.md`（子目录只认 `AGENTS.md`，不认 `CLAUDE.md`）。不在 `cwd` 底下就返回空。
- **触发时机**：不是预先全读，而是**agent 碰某个路径时**才加载——`ToolExecutor` 对每个带 `path` 参数的工具调 `on_path(path)`（`run.py` 里接的是 `context.note_path`）。同一路径只加载一次。

**为什么**：一个仓库可能有几百个目录的 AGENTS.md，全量塞进上下文会炸。惰性加载让「我要去那个目录了」和「我读到了那个目录的规矩」同步发生。

### a6 运行时状态怎么进上下文？权限模式中途变了怎么办？

**结论**：每一条都在**每次组装消息时现算**，不烤进 system prompt。

- **权限模式**：`ContextEngine._mode_text()` → `tools/permissions.py` 的 `mode_block(mode)`。只有 `plan` 和 `readonly` 两种模式有说明（其余三种没有额外说明）。之所以必须现算，是因为 `/mode`、`/plan` 会在**会话中途**原地改 `policy.mode`，烤进 system prompt 就成了过期信息。
- **todo**：`session.metadata["todos"]`，渲染成 `<current_todos>` 块，用 `- [x]` / `- [ ]` 复选框语法。
- **摘要**：`self.summaries`，渲染成 `<session_summary>` 块。

**为什么**：同一段 system prompt 必须在权限模式变化后立刻失真。实测踩过这个坑：最早 `plan` 和 `readonly` 两个模式对模型完全一样（空壳），模型不知道自己能做什么、不能做什么。

---

## b. 工具如何管理

### b1 内置工具有哪些？怎么启用/禁用？外部工具怎么进来？

**结论**：`tools/builtin/__init__.py` 的 `ALL_TOOLS` 有 **11 个**内置工具：

`read`、`write`、`edit`、`multi_edit`、`glob`、`grep`、`ls`、`bash`、`bash_output`、`bash_kill`、`todo_write`。

- **启用/禁用**：`config.tools.enabled`（白名单，默认全开）+ `config.tools.disabled`（黑名单），`build_registry(enabled, disabled)` 求交集。
- **外部工具**叠加在上面：`task`、`skill`（`run.py` 里条件注册）、MCP 工具（`mcp__<server>__<tool>`）、插件工具。
- `tools/registry.py` 的 `ToolRegistry` 是名字 → `Tool` 的字典；同名重复注册会告警并覆盖。

**为什么**：白名单 + 黑名单两条通道，是为了「全局开一个工具」和「全局关一个工具」都能一句话写出来。

### b2 工具 schema 占多少预算？怎么裁？

**结论**：`tools/registry.py` 的 `ToolRegistry.schemas(budget_tokens)`。

- **预算大小**：`run.schema_budget()` —— 配了 `tools.schema_budget_tokens` 就用它，否则 `max(context_window // 10, 内置工具本身的大小)`。也就是**默认给工具 schema 留窗口的 10%**。
- **估算**：`int(len(json.dumps(schemas)) / 3.5)`。
- **裁剪顺序**：`TRIM_ORDER` 从先丢 `web_search` / `web_fetch` / `todo_write` / `bash_output` / `bash_kill`，再到 `multi_edit` / `write` / `edit`，再到 `ls` / `glob` / `grep`，最后是 `read` / `bash`。
- **永不裁**：`NEVER_TRIM = {"bash", "read"}`。
- **两轮裁剪**：第一轮按顺序丢到放得下为止；第二轮如果还超，就反复丢**剩下里 schema 最大的那个**（`bash` / `read` 除外）。

**为什么**：`bash` 和 `read` 是 agent 的两条腿（行动和观察），砍掉任何一个 agent 都不会干活。`web_*` 最先丢是因为很多模型自带联网。

### b3 一轮多个 tool call，并行还是串行？

**结论**：`tools/executor.py` 的 `ToolExecutor.execute()`。

- **判定**：只要有**任意一个** action 属于 `SEQUENTIAL_TOOLS = {"bash", "write", "edit", "multi_edit"}`，或者只有一个 action → **串行**按序执行。否则 → `ThreadPoolExecutor(max_workers=len(actions))` 并行。
- **顺序保证**：`pool.map` 保序，所以结果**永远按模型给定的 tool_call 顺序**返回。
- **权限先算**：`_prepare()` 对**所有** action 先跑一遍（hook → 权限 → 审批），再开始执行。所以被拒的 action 不会执行，但也**不产生** `TOOL_RESULT` 事件——事件日志里只看到 `TOOL_CALL`，看不到它的结果。

**为什么**：读类工具（`read` / `grep` / `glob`）互不干扰，可以并行省时间；写类工具有顺序依赖，并行会打架。

### b4 工具执行失败会怎样？

**结论**：**不会中断整轮**。`executor.py` 的 `_run()`：

- 工具抛异常 → 变成一条 observation 字符串 `"Error: '<tool>' failed: <Type>: <msg>"`；
- 参数 JSON 解析失败 → 变成 `"Error: ..."`，并明确告诉模型「请发一个 JSON 对象」；
- 工具自己返回 `is_error=True`（比如 `old_string` 没找到）→ 同样是给模型看的一段错误文本。

模型看到的是**正常的 tool result**，只是内容是错误说明，它可以自己改正后重试。

**为什么**：让工具错误成为**模型可读的信息**而不是异常，是 agent 能自我纠错的前提。

### b5 有哪几种权限模式？默认判定是什么？

**结论**：`tools/permissions.py` 的 `PermissionMode` + `_default_decision()`。5 种模式：`default`、`acceptEdits`、`plan`、`bypass`、`readonly`。

工具被分成三类（`permissions.py` 顶部）：

- `READ_TOOLS = {read, glob, grep, ls}`
- `WRITE_TOOLS = {write, edit, multi_edit}`
- `INFO_TOOLS = {todo_write, bash_output, bash_kill}` —— 只动 agent 自己的记账，**任何模式都直接放行**

| 模式 | 读类 / 记账类 | 写类 | 其他（bash / task / skill / MCP） |
|---|---|---|---|
| `default` | allow | **ask** | **ask** |
| `acceptEdits` | allow | **allow** | ask |
| `plan` | allow | **deny** | **deny** |
| `readonly` | allow | **deny** | **deny** |
| `bypass` | allow | allow | allow |

**审批结果**有三种：`allow` / `deny` / `always`。选 `always` 会把一条 allow 规则**写进用户规则文件**（`rules.add_rule`），下次同一类操作不再问。

### b6 规则文件在哪？谁说了算？匹配语义是什么？

**结论**：`tools/rules.py`。

- **位置**：项目 `<project>/.coderagent/rules.yaml` 和用户 `<config_home>/rules.yaml`。
- **优先级**：**项目规则先、用户规则后，后写的赢**。也就是说用户可以覆盖项目的同名规则。
- **格式**：`{"rules": [{tool, pattern, decision, reason}]}`。只认这四个键，多一个就抛 `RuleError`（带文件名和行号）。`decision` 只能是 `allow` / `ask` / `deny`。
- **匹配语义**（`Rule.pattern`）：
  - **路径类工具**：`pattern` 是 **glob**，用 `glob_to_regex` 转成正则，对**相对 cwd 的路径**匹配。`*` 不跨 `/`，`**` 跨。
  - **`bash`**：`pattern` 是**正则**，而且必须匹配**整段的开头**（`git push` 不会匹配 `echo "git push"`）。
  - **其他工具**：`pattern` 是工具名，或者 `*`。
- **求值顺序**：非 bash 工具是「按顺序遍历所有规则，**最后一条匹配的赢**」；bash 是「**分段**判，每段最后一条匹配的赢，整条命令取**最严**的段」。这两处「最后一条赢」的作用域不同，是个容易看错的地方。
- **deny 永远赢**：`_strictest()` 定义 `allow(0) < ask(1) < deny(2)`。

### b7 `bash` 这种命令怎么管？

**结论**：`tools/bash_policy.py` + `permissions.py` 的 `_evaluate_bash()`。

1. **先看越界**：`outside_paths(command, cwd, include_dirs)` 找出命令要碰的、**工作目录之外**的路径。只要有，直接 deny——**在任何模式下都成立**（本地沙箱时 `bounded=True`）。
2. `bypass` → 直接 allow；`plan` / `readonly` → 直接 deny。
3. 其余模式：**按段判定**。`segments(command)` 是个手写扫描器，按 `&&`、`||`、`;`、`|`、换行切分，且**尊重引号**。
4. 每段先看规则；没有规则就看 `classify_segment(segment)`：
   - `safe` → allow（`git status`、`ls`、`cat` 等在 `COMMANDS` 表里且没有危险说明）；
   - `dangerous` / `unknown` → **ask**（`git push` 是 dangerous；任何带 `/` 的程序名、带重定向的段都是 unknown）。
5. 整条命令取**最严**的那一段。

**为什么**：不能只对整条命令做正则匹配——`echo hi && rm -rf /` 里危险的是后半段。所以要切段，要逐段判，要取最严。

**注意**：`bash` 规则**在 `bypass` 模式下完全失效**（第 2 步就返回了）。评测任务想用 bash 规则保护文件，就必须让那个任务用 `mode: default`。

### b8 `edit` / `multi_edit` 的硬性保证？

**结论**：`tools/builtin/fs.py`。

- **`edit`**：`old_string` 必须**恰好出现一次**。出现多次 → 报错并告诉模型出现了几次、在第几行，建议加上下文或用 `replace_all=True`；一次都没出现 → 报错「用 `read` 看看原文再带更多上下文重试」。文件是 CRLF 而 `old_string` 不是时，会自动试 CRLF 变体。
- **`multi_edit`**：**原子**。所有编辑先在内存副本上应用，全部成功才落盘；任何一条失败就返回「Edit #N failed, no changes were written」，文件一个字节都不动。
- **`write`**：整体覆盖，会建父目录。
- **读类工具的输出有上限**：`read` 默认 2000 行，超过 2000 字符的行会被截断并标出来；`glob` 最多 200 条路径；`grep` 最多 100 行内容；`bash` 输出按 `tools.max_output_tokens`（默认 8000）裁剪。

**为什么**：`edit` 的「唯一匹配」是 agent 改文件时最容易出错的地方（改错位置）。宁可让它失败要求重试，也不要让它猜。

### b9 模型的一次工具调用，是怎么一步步跑下来的？

**结论**：从模型返回到结果回到模型，一共 6 步，分布在两个文件里。

1. **取**：`core/loop.py:206` 从 assistant 消息里取 `tool_calls`。没有 `tool_calls` 就意味着模型说完了，这一轮结束（或者进入 verify 重试）。
2. **规整**：`executor.plan()`（`executor.py:51`）把原始 tool call 变成统一形状：`{"tool", "tool_call_id", "args", "raw"}`。这一步只做 JSON 解析——参数不是合法 JSON，或者解析出来不是**对象**，就在这里记下 `error`，**不会走到执行**。
3. **记账**：`loop.py:225` 发一个 `TOOL_CALL` 事件，**在执行之前**。事件里是全部 action 和它们的参数——所以「模型打算干什么」永远早于「它干了什么」被记下来。被拒的 action 也会出现在这里。
4. **准备**：`executor._prepare()`（`executor.py:93`）对每个 action 依次做四件事：
   - **查注册表**：`registry.get(name)`，找不到就直接记错（见 b10）；
   - **PreToolUse hook**：可以阻断，也可以改写参数（改写后的参数才是被权限判定的那一份）；
   - **权限判定**：`policy.evaluate(tool, args)`；
   - **审批**：`ask` 的去问 approver（headless 下由 `HeadlessApprover` 回答）。
5. **执行**：`_run()`（`executor.py:149`）——先 `on_path`（让上下文引擎捡起该目录的指令），写类工具先 `before_write`（打 checkpoint），然后 `tool.run(args, ctx)`。工具抛异常 → 变成给模型看的错误文本（见 b4），**整轮不中断**。
6. **回话**：结果发 `TOOL_RESULT` 事件（含 diff），observation 一定带 `tool_call_id`（`executor.py:178`），模型才能把结果对上号。

**为什么**：权限和 hook 都在**执行之前**判定，所以「被拒绝的工具」永远不会真的动过文件；而 `TOOL_CALL` 在执行之前记账，所以事后复盘时能看出模型**本来想做什么**——这两件事都是评测「模型乱调工具」的依据。

### b10 模型会自己造不存在的工具，或者乱调工具吗？

**结论**：**会**，但每一类都有确定的落点，而且**不会有任何越界的副作用**。

**造工具（调一个不存在的名字）**：`executor.py:97` 查注册表，查不到 → observation 变成
`Error: unknown tool 'xxx'. Available tools: read, write, edit, ...`。
**工具不会执行**，模型看到的是一段普通的 tool result（带 `tool_call_id`），下一轮它要么改用真名字，要么就卡在那儿反复试。
已注册的工具**只有注册表里的那些**——MCP 工具叫 `mcp__<server>__<tool>`，插件工具用插件自己的名字，模型凭空说的名字不在表里。

**乱调（调了不该调的工具）**：由三层挡：

| 层 | 挡住什么 |
|---|---|
| 权限模式 | `plan` / `readonly` 下写类工具**直接 deny**；`default` 下写类工具要 ask；`bypass` 下才全放行 |
| 规则文件 | 项目 / 用户的 `rules.yaml` 可以对具体工具 + 路径给 allow / ask / deny，deny 永远赢 |
| 越界检查 | `within_bounds()` 在**任何模式**（含 `bypass`）下都挡住工作目录之外的路径 |

**bash 的特殊处理**：命令按 `&&` / `||` / `;` / `|` / 换行切段（尊重引号），逐段判定，整条命令取**最严**的一段。所以 `echo hi && rm -rf /` 不会因为前半段安全就放行。

**参数不对**：工具自己做类型检查（`fs.py` 里 `path` 必须是 str、`old_string` 必须是 str、`multi_edit` 的 `edits` 必须是 list……），不满足就报错；类型转换类的异常（比如把 str 当 int 用）在 `executor.py:160` 被兜住，变成给模型看的错误文本。

**子 agent**：白名单之外的工具在子 agent 的注册表里**根本不存在**（`core/subagent.py:195`），所以子 agent 也调不到。

**怎么发现模型乱调**：
- `TOOL_CALL` 事件在执行前记下全部参数——事后能逐条回看模型「想干什么」；
- 评测报告里的 `tool_errors` 数失败的工具调用（被权限拒绝的也算）；
- `require_tools` 要求某些任务**必须**用某个工具改某个文件（`evals/basic` 里五个任务这样写）——用 shell 绕过去不算完成；
- `no-op` 任务反过来测「不该改的时候别改」。

**为什么**：模型是概率的，它一定会偶尔喊错工具名、偶尔调错参数。harness 的责任不是让模型永不犯错，而是**让每次犯错都变成模型能读懂的普通消息，并且有确定的后果边界**（不执行、不越界、留痕）。

---

## c. 任务如何调度

### c1 一轮 turn 的主循环长什么样？

**结论**：`core/loop.py` 的 `AgentLoop.run_turn(user_input)`。

1. **UserPromptSubmit hook** 先跑（hook 可以改写用户提问，也可以直接拦下整轮）；
2. 用户消息进上下文，`session.turn_count += 1`，状态 → `THINKING`；
3. `while True`：
   - 检查 `cancel`（见 c4）；
   - 检查 `max_turns` / `cost_limit` / `token_limit`（见 c3）；
   - 路由选模型（见 c6）→ `maybe_compact()` → 问模型；
   - 模型返回**工具调用** → `executor.plan()` + `execute()` → 工具结果回灌上下文 → 继续下一轮；
   - 模型返回**纯文本**（没有 tool call）→ 这一轮就结束（`end_turn`）。

**关键点**：一次「用户输入」对应**很多次模型调用**（`max_turns` 数的是模型调用次数，不是用户轮数）。`TurnResult.turn_count` 才是用户轮数。

### c2 一轮会以哪些原因结束？

**结论**：`stop_reason` 共 7 种：

| stop_reason | 含义 |
|---|---|
| `end_turn` | 模型不再要求调工具，这轮结束 |
| `interrupted` | `cancel()` 返回 True（用户中断 / 评测超时） |
| `max_turns` | 模型调用次数达到 `agent.max_turns` |
| `cost_exceeded` | 本会话花费达到 `agent.cost_limit` |
| `token_limit` | 本会话 token 达到 `agent.token_limit` |
| `error` | 模型调用失败，或上下文溢出且压不动了 |
| `verify_failed` | 验证命令在 `verify.max_rounds` 轮之后仍然失败 |

**注意**：`end_turn` **不等于成功**。模型可以什么都没干就停。成功与否由外部的验证命令决定（评测里就是 `verify`）。

**已知瑕疵**：`TurnResult.stop_reason` 的 docstring 只列了 5 种，漏了 `interrupted` 和 `verify_failed`。

### c3 跑太久 / 轮数多 / 花钱多，怎么卡住？

**结论**：`core/loop.py` 在每轮循环顶部依次检查。

- `agent.max_turns`（默认 50，0 = 不限）——**模型调用**上限。
- `agent.cost_limit`（默认 0.0 = 不限）。
- `agent.token_limit`（默认 0 = 不限）。
- 附加提醒：`_warn_unpriced()`——如果模型没有价格表却配了 `cost_limit`，会提示改用 `agent.token_limit`（很多自建端点没有价格，cost 恒为 0）。

**取舍**：`max_turns` 数模型调用而不是工具调用，因为真正烧钱的是模型调用。

### c4 一轮进行中怎么被打断？

**结论**：`AgentLoop.cancel` 是一个**公开扩展点**（`self.cancel = None`），每轮循环顶部调一次，返回 True 就以 `interrupted` 结束。

三个使用者：

- **TUI**：`loop.cancel = self.interrupted.is_set`（按 Esc 置位）；
- **Web 版**：`threading.Event`；
- **评测**：`loop.cancel = lambda: time.monotonic() > deadline`，`deadline = now + task.timeout`（默认 300 秒）。

**为什么**：把「打断」做成一个可注入的回调，而不是在循环里写死某一种中断源——这样同一个循环能同时被界面、网页和评测三种外部节奏驱动。

### c5 子 agent 怎么调度？和主 agent 什么关系？

**结论**：`core/subagent.py` 的 `SubAgentRunner`，由 `task` 工具触发。

- **定义**：markdown + YAML front matter，放在 `.coderagent/agents/*.md`（项目）或 `<config_home>/agents/*.md`（用户），**项目优先**。front matter 字段：`name`、`description`、`tools`、`model_purpose`、`max_turns`。正文就是 system prompt。
- **内置三个**：`code-explorer`（`read/grep/glob/ls`，15 轮）、`verifier`（`read/grep/glob/bash`，20 轮）、`refactorer`（`read/edit/grep/glob`，30 轮）。
- **和主 agent 的关系**：
  - **不共享上下文**。子 agent 自己起一份 `[system, user]` 消息（`subagent.py` 的 `messages = [system, user]`），看不见主对话。
  - **不共享工具**。它有一份**白名单**工具表（`_restricted(spec)` 另建一个 `ToolRegistry`）。
  - **不共享轮数**。自己的 `max_turns`（默认 20）。
  - **共享权限模式**，而且这个模式说明被写进子 agent 的 system prompt，让它知道自己和主 agent 一样受限。
  - **共享事件总线和会话 id**，所以子 agent 的行为在主会话里看得见。
- **成本归属**：子 agent 报回自己的 `cost = gateway.total_cost - before`（**只算它自己那几次调用**）。如果它跑在**另一个** gateway（不同模型）上，这个差额会**加回主 gateway**，主会话的总账因此是对的。
- **子 agent 的 tool call 不进事件日志**（只发到总线），所以从日志里看不出它改过哪些文件；它的**结果 JSON**里有 `files_touched`，但只统计 `write`/`edit`/`multi_edit`。

**为什么**：子 agent 的价值是**隔离上下文**——让它去看 50 个文件，主对话只拿到一份结论。它的工具白名单是第二道安全边界。

### c6 模型可以中途换吗？依据是什么？

**结论**：`models/router.py` 的 `ModelRouter`，每轮循环开头调一次。

- **四个维度**：`purpose`（main / cheap / strong / summarize / reflect）、`complexity`、`budget`、`user_override`。
- **优先级**：用户显式指定的模型 > `config.model.routing[purpose]` > 默认 main。
- **默认策略**：预算用掉 80%（`cost >= budget * 0.8` 或 `tokens_used >= token_budget * 0.8`）→ 降到 `cheap`；上下文超过 50000 token 或会话超过 30 轮 → 升到 `strong`。
- **自定义规则**：`model.routing_rules`，每条形如 `when: "tokens > 10000"` + `purpose: strong`。**只比较数字**，`>`、`>=`、`<`、`<=`、`==`、`!=` 六种；**绝不 eval**，所以配置文件跑不了代码。
- **换模型时发一条 `STATE_CHANGE` 事件**（`model` / `previous` / `reason`），事件日志里能看到「为什么换的」。
- **坑**：`ModelRouter.backend_for()` **每次都新建一个 backend**。所以 `loop._route()` 比较的是**解析后的真名**而不是别名，否则每轮都会重建 backend，别名解析还会失效。

### c7 todo 列表存在哪儿？怎么回到上下文？

**结论**：`tools/builtin/todo.py`。

- 状态在 `session.metadata["todos"]`；`todo_write` 每次**整体替换**列表。
- 每项 `{content, status, activeForm}`，`status ∈ {pending, in_progress, completed}`，`content` 和 `status` 必填，校验不过返回 `is_error`。
- 渲染进上下文的是 `<current_todos>` 块（`- [x]` / `- [ ]`）。
- `todo_write` 属于 `INFO_TOOLS` → **任何模式都放行**，不问人。
- **可重放**：`SessionStore.rebuild()` 从任何带 `todos` 的 `TOOL_RESULT` 事件里恢复 todo 列表。

**为什么**：让 agent 自己把大任务拆成可见的步骤，是它不掉链子的主要手段；但它只动 agent 自己的记账，所以不该占用审批预算。

---

## d. memory 和 state 如何管理

### d1 「state」指什么？有哪几种？

**结论**：`core/session.py` 的 `SessionState`：`IDLE`、`THINKING`、`EXECUTING`、`AWAITING_APPROVAL`、`DONE`、`ERROR`。

状态流转：`THINKING`（等模型）→ `EXECUTING`（跑工具）→ `THINKING` → …… 结束时按停止原因落 `DONE` 或 `ERROR`；审批时短暂进 `AWAITING_APPROVAL`。每次变化发一条 `STATE_CHANGE` 事件。

会话的**其他状态**（不是状态机，而是数据）：`turn_count`、`total_cost`、`total_tokens`、`metadata`（装 todo）、`cwd`、`model_name`、`permission_mode`。

### d2 事件日志是什么？格式？为什么是「唯一事实来源」？

**结论**：`core/events.py` + `core/session.py`。

- **文件**：`<config_home>/sessions/<session_id>.jsonl`，**一行一个 JSON 对象**：`{"type", "session_id", "timestamp", "payload"}`。
- **事件类型**（`EventType`，16 个）：`user_message`、`assistant_message`、`text_delta`、`reasoning`、`tool_call`、`tool_result`、`approval_request`、`approval_response`、`state_change`、`turn_end`、`verify`、`compaction`、`reflection`、`reverted_to`、`error`。其中 `text_delta` / `reasoning` **只发总线、不写日志**（流式文本太碎，会把日志撑爆）。
- **会话 id**：`YYYYMMDD-xxxxxx`（日期 + 6 位 hex）。
- **写入**：每行 flush + `os.fsync`。
- **为什么唯一**：**钱、token、上下文、todo 都不另存一份**，全部从事件日志重放算出来。`rebuild()` 重放时顺带算出 `metrics = collect(events)`，成本和 token 直接取自日志。
- **容错**：坏行只跳过并告警，不报废整个会话。

**为什么**：一份日志同时回答「当时发生了什么」「花了多少钱」「现在对话到哪了」「怎么恢复」，比维护四份状态互相同步要可靠得多。

### d3 关掉程序能接着聊吗？

**结论**：能。`SessionStore.rebuild(session_id)` 重放 JSONL，恢复对话历史、摘要、todo、状态、成本。

- **`/resume`**（`ui/commands/resume.py`）：列出会话、`latest_session()` 取最近一个、`resume()` 就是 `store.rebuild()`。
- **切到旧会话**：`AgentLoop.switch_to(session)` 重建 `ContextEngine`（带着 config、memory 配置、摘要模型、权限策略），然后 `context.restore()`——历史和摘要从日志里**重放**回来（包括 `COMPACTION` 事件的截断、`REVERTED` 事件的回退）。
- **分叉**：`store.fork(session_id)` 把整个事件日志复制到新会话 id，原会话**一个字节都不动**。

**取舍**：对话状态是从日志**重算**出来的，不是存出来的。好处是没有「两份状态不一致」这种 bug；代价是恢复的代码必须跟着事件格式走。

### d4 检查点存什么？能回退到什么粒度？

**结论**：`core/checkpoint.py`。

- **内容**：`Checkpoint` 里有 `id` / `timestamp` / `turn` / `kind` / `payload` / `messages` / `redacted`。
  - `payload` 是 `{路径: 旧内容}`，`None` 表示「这个文件当时还不存在」；
  - `messages` 是**当时的对话消息数**——用来回退对话；
  - `redacted` 是**存不下**（含密钥）的路径列表。
- **位置**：`<config_home>/checkpoints/<session_id>.json`，一个会话一个文件，里面是一串检查点。文件权限 `0600`（里面是项目文件的内容）。
- **何时产生**：每次写文件**之前**自动拍一个（`before_write` 回调，`run.py` 里接的 `create_file_checkpoint`），由 `config.checkpoint.enabled` 控制。
- **保留**：`checkpoint.keep`（默认 50），超了丢最老的。
- **回退**：`restore_files(checkpoint, cwd)` 把旧内容写回去；「当时不存在」的文件被**删掉**；**被脱敏的路径跳过**（没法精确还原）。

**为什么**：对话能回退、文件不能，是 agent 最常见的翻车现场。检查点把「文件系统的历史」补上了。

### d5 「memory」有几层？谁读谁写？

**结论**：四层。

| 层 | 位置 | 读 | 写 |
|---|---|---|---|
| 工作记忆 | `session.metadata["todos"]` | `context.py` | `todo_write` 工具 |
| 会话记忆 | `<session_summary>` 块 | `context.py` | 压缩时生成 |
| 项目记忆 | `<cwd>/.coderagent/memory/*.md` | `core/memory.py` | `extensions/reflect.py` |
| 用户记忆 | `<config_home>/CLAUDE.md` | `core/memory.py` | `extensions/reflect.py`（**要确认**） |

- `core/memory.py` 本身是**只读**的（它只负责把项目记忆和用户记忆读成 `InstructionBlock` 塞进上下文）。
- 写发生在 `extensions/reflect.py`，由 `run.settle_session()` 在**会话结束时**触发：
  - 模型被要求输出 JSON：`{"project_facts": [...], "user_preferences": [...]}`；
  - **项目事实**直接写进 `<cwd>/.coderagent/memory/projects.md`（去重后追加，最多 200 行，超了拒写并告警）；
  - **用户偏好**不直接写：要么 `/memory confirm` 确认后写进用户 `CLAUDE.md` 的 `## Preferences` 段，要么落到 `<cwd>/.coderagent/pending-memory.md` 等确认；
  - `/memory forget <文本>` 可以从项目记忆或待确认文件里删掉一行。
- 整个 `settle()` **吞掉所有异常**——「这里的失败不能毁掉这一轮运行」。
- 反思的成本会记成一条 `EventType.REFLECTION` 事件，并加进会话总账。

**为什么**：项目事实可以直接写，用户偏好必须确认。用户偏好会永久改变 agent 的行为，不该由一次会话自己决定。

### d6 用户级数据散落在哪些路径？评测怎么隔离？

**结论**：`paths.py` 的 `config_home()` 是**唯一总开关**：

```python
config_home() = Path(os.environ["MSWEA_CODER_HOME"]) if 设置了 else Path.home() / ".coderagent"
```

它管住：`sessions/`、`checkpoints/`、`config.yaml`、`rules.yaml`、`agents/`、`skills/`、`plugins/`、`trusted-plugins.json`、`CLAUDE.md`。

**项目级的**（`<cwd>/.coderagent/` 下的 agents、skills、plugins、rules.yaml、memory/、pending-memory.md、commands/）**不在**这个开关里。

**评测的隔离**（`ui/cli.py` 的 eval 命令）：

1. **先** `load_config()`——用户的模型名和 api_key 在 `~/.coderagent/config.yaml`，必须先读到；
2. **再** `os.environ["MSWEA_CODER_HOME"] = <run-dir>/home`；
3. `SessionStore(<run-dir>/home/sessions)` 显式传根目录。

**顺序反了就废了**：先重定向就读不到用户的模型配置了。

**注意**：`CheckpointStore` 和 `load_rules` 只看 `config_home()`，不看 `build_loop(user_home=...)`——所以**两个都要设**，环境变量才是生效的那个。

---

## e. 如何做评测与如何观察

### e1 有没有跑一批任务并自动判分的入口？任务怎么写？

**结论**：有，`coder eval <suite>`。

**任务格式**：一个 suite 是一个目录，每个子目录一个任务，里面必须有 `task.yaml`；其余文件（除 `*.yaml`/`*.yml`）是 **fixture**，会被复制成 agent 的初始工作目录。

`task.yaml` 字段：

| 字段 | 必填 | 含义 |
|---|---|---|
| `prompt` | | 给 agent 的用户请求 |
| `prompts` | | 给 agent 的多个请求，一个接一个，同一会话。**只有一个 prompt 的任务永远不会压缩**——切点必须落在轮边界上 |
| `verify` | **是** | 判定用的命令，**全部退出码 0 才算通过**；没有 verify 的任务永远不算通过 |
| `setup` | | agent 开始前在 workdir 里跑的命令 |
| `expect` | | `pass`（默认）或 `fail`——保险丝 |
| `timeout` | | agent 这一轮的墙钟秒数（默认 300） |
| `verify_timeout` | | 每条 verify 命令的秒数（默认 300） |
| `tags` | | 给 `--tag` 过滤用 |
| `require_tools` | | 「这个任务必须用某个工具在某个文件上干成」 |
| `script` | | 脚本化模型；**空 = 用真实模型**（要 API key） |
| `config` | | 配置覆盖：YAML 文件路径或 `a.b=c` |

`require_tools` 是本项目的关键设计：`{tools: [edit, multi_edit], paths: [calc.py]}` —— 任务不仅要有 verify 命令，还要**用对的工具在对的文件上**干成事。判定靠 `eval/runner.py` 的 `_successful_calls()`：只有**没有报错的** tool call 才算数，工具名要在白名单里、路径要在名单里（路径按 workdir 解析）。

**两个 suite**：`evals/basic/` 9 个任务（全部要 API key）、`evals/offline/` 6 个任务（全部带 `script:`，**不要 API key**）。`evals/offline/broken-check` 是 `expect: fail` 的保险丝。`evals/basic/long-conversation` 是唯一会触发压缩的任务：它有四个 prompt，并把自己的窗口调小，逼着 harness 压缩。`evals/offline/multi-turn` 是多轮的离线版：三个 prompt，同一个会话，三轮。

### e2 怎么保证「agent 的失败」和「harness 的失败」分得开？

**结论**：`eval/runner.py` 用 `error_kind` 区分三种情况：

- `"setup"` —— **harness** 的 setup 命令失败了。这不是 agent 的锅：这个任务**不计入**通过率分母，在报告里单列。
- `"script"` —— 脚本化模型把脚本用完了（错误里含 `"ran out of responses"`）。同样是 harness 的锅。
- 空 —— **agent 自己的失败**。计入分母。

**隔离**：每个任务一个独立工作目录（`root/work/<task-id>`），整个 suite 一个独立的 `MSWEA_CODER_HOME`（`root/home`），所以会话、检查点、规则都不会跑到用户目录里。

**其它几个坑**（都已在代码里处理）：

- 用 `build_loop` + `loop.run_turn`，**不走** `run.py` 的 `run_turn()`——后者结尾会 `settle()`，多一次 reflection 调用，会**吃掉脚本的下一条响应**，还会往被测目录里写记忆文件。
- 脚本模式下清掉 `config.model.routing`（否则长上下文会把脚本换成真模型）和 `config.context.auto_compact`（压缩会消耗一条脚本响应）。
- `build_loop` 会**改写传进去的 Config**，所以**每个任务重新 `load_config`**。
- setup / verify 用 `CodingEnvironment`（去掉了 mini-swe-agent 的 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 哨兵）跑，不要用 `bash` 工具跑——它会裁剪输出、加 `[exit code N]` 装饰。

### e3 报告里有什么？fingerprint 是什么？

**结论**：`eval/report.py`，格式 `coder-eval-1.0`。

JSON 顶层：`format`、`label`、`suite`、`model`、`fingerprint`、`config`、`started_at`、`duration_seconds`、`summary`、`tasks[]`。

`summary`：`tasks`、`passed`、`failed`、`errors`、`unexpected`、`pass_rate`、`total_cost`、`total_tokens_in`、`total_tokens_out`、`total_model_calls`、`total_tool_calls`、`compactions`、`summary_ratio_mean`、`summary_ratio_max`。

`summary_ratio` = 摘要多大 / 它替换掉的那段历史多大，一次压缩一个数，落在 `tasks[].summary_ratios` 里。**这个比值是摘要质量的仪表盘**：突然变大，要么是摘要变啰嗦了，要么是被摘的那段变啰嗦了。

**fingerprint** = `sha256:` + 对一组**配置**做的哈希。输入包括：`model` 和 `model.routing`、`agent.system_prompt` / `max_turns` / `cost_limit` / `token_limit`、`tools.enabled` / `disabled`、`permissions.mode` / `rules` / `deny_paths`、整个 `context` 配置、`sandbox.type`、**每个任务的 config 覆盖**、**每个任务的 require_tools**。

**为什么**：fingerprint 相同才说明两次跑的是同一套 harness，数字才可比。不同就说明「harness 变了，数字自然变」，不能拿来算退化。而且报告里同时放了 fingerprint 的**输入原样**，外部 diff 能直接看出**是哪一项**变了。

**注意事项**：报告里**不放临时工作目录路径**（每次都变，会毁掉 diff）；只用 task id 和相对路径。成本可能是 0（litellm 没有这个模型的价格表），所以 **token 数必须一起报**，它来自 provider 的 usage，靠得住。

### e4 两次运行怎么比？

**结论**：`coder eval-compare <after.json> --against <before.json>`，实现在 `eval/compare.py`。

- 报出：`regressions`（之前过、现在不过的任务）、`improvements`、`only_before` / `only_after`（只出现在一边的任务）、`before_pass_rate` / `after_pass_rate` / `drop`、`config_changed`、`unexpected`（结果和 `expect` 不符）、`broken_guards`（`expect: fail` 的保险丝反而过了）、`ungraded`。
- **判定**：`verdict(comparison, max_regressions, max_drop)` —— 退出码就是结论（有回归就退 1）。
- `--same-config`：两次 fingerprint 不同就明确说「这两次跑的不是同一套配置，比不了」，而不是给一个没意义的结论。
- `expect: fail` 的任务**不计入**通过率。

**为什么**：这是整个 eval 的**交付物**——不是「跑通了一堆任务」，而是「能自动告诉你上一次改动让 agent 变差了」。

### e5 一次真实会话怎么观察？

**结论**：`core/telemetry.py`。

- **`collect(events)`** 从事件日志算出 `Metrics`：`total_cost`、`total_tokens_in/out`、`model_calls`、`tool_calls`、`per_tool`、`per_purpose_cost`、`per_model_cost`、`duration_seconds`、`compactions`、`errors`。
  - 子 agent 的成本从 `task` 工具结果 JSON 里捞回来，单独记在 purpose `subagent` 下；
  - 压缩摘要的成本记在 purpose `summarize`；反思记在 `reflect`。
- **导出**：`coder export --format json|otel`。JSON 是 trace 格式 `coder-agent-1.0`（`{session, events, metrics}`）；OTLP 是 OTLP/JSON，**一个 user turn 一个 span，每次工具调用一个子 span**。
- **会话里的实时观察**：TUI 状态栏（模型、token 用量、成本、cwd、权限模式）、`/cost`、审批弹窗、Web 版的 SSE 流。

**注意**：`model_calls` 只数主循环的响应，子 agent 的调用不在里面（它的成本在 `per_purpose_cost` 里）。别夸大。

### e6 CI 里跑的是什么？

**结论**：`.github/workflows/eval.yaml`。

- **触发**：对 `main` 的 PR，且改了 `src/coderagent/**`、`evals/**`、`tests/coderagent/**` 或该 workflow 本身；另外支持手动触发（可以传 `live` 开关和 `model` / `api_base`）。
- **必跑 job `harness`**：跑 `coder eval evals/offline`（**不需要 API key**），再用 `git worktree` 把 base commit 拉出来、用 `PYTHONPATH` 指过去跑一遍同样的 suite，然后 `coder eval-compare head.json --against base.json`。**base 没有 eval 命令就跳过**。
- **手动 job `live`**：跑 `evals/basic`（需要 `secrets.CODER_EVAL_API_KEY`），加 `--same-config --max-regressions 0 --max-drop 0`。

**为什么**：PR 门禁用离线 suite——它测的是 **harness 本身**（工具、权限、事件日志、执行器），不需要花钱也不需要凭据，是最划算的回归网。

---

## f. 如何做约束以及恢复

### f1 约束一共有几层？

**结论**：六层，从粗到细。

| 层 | 管什么 | 在哪 |
|---|---|---|
| **权限模式** | 一刀切：这次会话允许做什么 | `permissions.mode` |
| **规则** | 按工具 + 路径 / 命令模式细粒度 allow/ask/deny | `rules.yaml`、`permissions.rules` |
| **`deny_paths`** | 指定路径全局拒绝，**任何模式下都拒**，且排在所有规则之后（能覆盖掉前面的 allow） | `permissions.deny_paths` |
| **`include_dirs`** | 显式打开工作目录之外的目录 | `permissions.include_dirs` |
| **hook** | 六个时点上的自定义检查与改写 | `hooks.events` |
| **沙箱** | 命令实际跑在哪 | `sandbox.type` |

**边界规则**（`within_bounds`）：路径类工具访问工作目录外的路径 → deny，**在任何模式下都成立**，**用户规则也不能开**（`allow` 一条越界的路径规则，它依然是被拒的）。`include_dirs` 里的目录是显式开的口子。

**bash 的对应检查**：`bash_policy.outside_paths()` 找出命令要碰的越界路径；`/bin` `/usr` `/lib` `/opt` 这些系统前缀**只允许作为程序**，不允许作为数据路径。

**容器沙箱例外**：`bounded = config.sandbox.type == "local"`。在容器里，边界由容器自己管，所以不再做路径越界检查。

### f2 hook 有哪几个触发点？hook 自己挂了会挡住操作吗？

**结论**：`extensions/hooks.py`，六个点：

| Hook | 时机 | payload | 能不能挡 |
|---|---|---|---|
| `SessionStart` | 会话开始 | `session_id`, `cwd` | 否（只通知） |
| `UserPromptSubmit` | 收到用户提问 | `prompt` | **能**（整轮终止） |
| `PreToolUse` | 工具执行前 | `tool`, `params` | **能**（工具不执行） |
| `PostToolUse` | 工具执行后 | `tool`, `params`, `result` | 只能换输出，**副作用已经发生** |
| `Stop` | 模型想停 | `last_message` | **能**（让 agent 继续干） |
| `SessionEnd` | 会话结束 | `session_id`, `turns`, `cost` | 否 |

- **决策值**：`allow` / `deny` / `block`（`deny` 和 `block` 都算挡住）；`reason`、`additionalContext`、`updatedInput` 也支持。
- **合并**：多个 hook 里只要有一个 deny/block 就挡；`allow` 只在没人决定时才生效；`additional_context` 拼接；`updated_input` **最后一个赢**。

**fail-open vs fail-closed**（这是刻意的分界）：

| hook 出问题 | 结果 |
|---|---|
| 超时 | **忽略**（放行） |
| 退出码非 0 | **忽略**（放行）——除非该 hook 配了 `strict: true`，此时 deny |
| 输出不是合法 JSON | **忽略**（放行），记一条警告 |
| matcher 正则写错 | 跳过该 matcher，告警 |

**为什么**：hook 是**用户自己加的辅助**，不是安全边界。安全边界是权限层和 `within_bounds`——那些是 fail-closed 的。hook 挂了就挡住操作，用户会得到一个「agent 什么都不干」的系统，却不知道为什么。

**唯一的例外**：`strict: true` 是用户显式说「我这条 hook 挂了就要挡住」。

### f3 hook 改写参数和改写提问，怎么区分？

**结论**：**按 `updatedInput` 的类型区分**。

- **dict** → 改**工具参数**（`PreToolUse` / `PostToolUse`）。`executor.py` 里用 `isinstance(hook.updated_input, dict)` 守住这条线：字符串**永远动不了**工具参数。
- **字符串** → 改**用户提问**（`UserPromptSubmit`）。`loop.py` 里只接受字符串。

**事件日志存的是模型看到的那一个**：hook 改写后的提问写进 `USER_MESSAGE` 事件的 `content`，用户原话放在同一事件的 `original` 里。这样**重放能复现同样的行为**。

### f4 出错之后能恢复吗？

**结论**：三种恢复，覆盖三种不同的需求。

| 手段 | 恢复什么 | 怎么用 |
|---|---|---|
| **`/rewind`** | 文件 **+** 对话 | `rewind(context, checkpoints, id, cwd)`：`restore_files()` 把文件写回旧内容（当时不存在的文件删掉），`context.rewind_to(checkpoint.messages)` 截断对话并发一条 `REVERTED` 事件 |
| **`/resume`** | 对话 | `store.rebuild(session_id)` 重放日志；`/resume` 列出并切回旧会话 |
| **分叉** | 一条新分支 | `store.fork(session_id)` 复制全部事件到新会话 id，原会话不动 |

**不能恢复的**：

- **`/rewind` 只回退文件，不回退外部世界**——命令发出去的网络请求、装过的包、删掉的东西，都还在。
- **被脱敏的路径不还原**（含密钥的文件存不下原样）。
- **会话级的东西**（成本、token）不回滚——历史已经花掉的钱就是花掉了。

**为什么**：诚实地划出「能回退什么」，比假装能时光倒流要安全得多。

### f5 三种失败分别怎么处理？

**结论**：

**（1）模型调用失败**（`loop.py` 的 `_query`）：

- **上下文溢出**是唯一可恢复的：强制压缩一次，然后**重试一次**；压不动就返回错误（文本里带 "nothing left to compact"）。
- **其它异常**：不重试（在 backend 层就已经过滤了不该重试的异常），直接发一条 `ERROR` 事件，`stop_reason="error"`，会话状态落 `ERROR` 而不是 `DONE`，错误消息留在日志里。

**哪些异常不重试**（`models/backends.py` 的 `abort_exceptions`）：`UnsupportedParamsError`、`NotFoundError`、`PermissionDeniedError`、`ContextWindowExceededError`、`AuthenticationError`、`BadRequestError`、`KeyboardInterrupt`。其它（比如中转站 500）**会重试**，默认 10 次、约 2 分钟。

**（2）工具失败**：**不中断整轮**，变成 `"Error: …"` 的 observation 给模型看（见 b4）。

**（3）摘要失败**：重试一次，再失败就兜底摘要（见 a4）。

### f6 沙箱管得住什么？边界在哪？

**结论**：`core/sandbox.py` 的 `build_environment(config.sandbox, cwd)`。

- `sandbox.type == "local"` → `CodingEnvironment(cwd=会话目录)`，就是本机 subprocess。
- 其它类型 → 走 mini-SWE-agent 的环境（`swerex_docker`、Modal、bubblewrap、contree），`SandboxConfig` 是 `extra="allow"`，`image` 之类的参数直接透传。

**管住的**：只有 `bash`（以及 verify 命令）进沙箱。

**管不住的**：`read` / `write` / `edit` / `glob` / `grep` / `ls` 这些文件系统工具**直接操作宿主机文件系统**。

**边界的实际形状**：

- 本地沙箱时，靠 `within_bounds` 把文件类工具挡在工作目录内，靠 `outside_paths` 把 bash 里的越界路径挡掉；
- 容器沙箱时，路径不设限（`bounded=False`），边界由容器自己给；
- 远程沙箱有自己的 `cwd`（`sandbox.cwd` 可配），不会把宿主机路径塞进容器。

**还有一个容易忘的点**：`CodingEnvironment` 去掉了 mini-SWE-agent 的 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 哨兵——「coding agent 结束一轮是因为模型说完了，不是因为某个命令打印了魔法字符串」。

---

## 已知瑕疵（写下来是为了不被当成没看见）

1. **相邻的两条 user 消息**：权限模式说明和摘要被组装成两条连续的 `user` 消息，中间没有 assistant。合法但不是自然对话形态。
2. **`stop_reason` 的 docstring 过期**：`TurnResult.stop_reason` 只列了 5 种，实际有 7 种（漏了 `interrupted` 和 `verify_failed`）。
3. **`_cut_index` 用的是 `config.context_window` 而不是 `guard.limit()`**：两者差一个 `reserved_output`，极端情况下会切得偏保守。
4. **「最后一条规则赢」有两个作用域**：路径类工具是「所有规则里最后一条匹配的赢」，bash 是「每段最后一条匹配的赢，再取最严的段」。
5. **`model.max_retries` 没接进 backend**：只有 `coder web` 读它；终端里想缩短重试只能用环境变量 `MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT`。
6. **子 agent 的 tool call 不进事件日志**：只发总线，所以从日志看不出子 agent 动过哪些文件（它的结果 JSON 里有 `files_touched`）。
7. **`core/memory.py` 是只读的，但「memory 特性」不是**——写入发生在 `extensions/reflect.py`，由 `settle_session()` 驱动。
8. **被裁掉的工具仍然能执行**：`registry.schemas()` 裁的是**发给模型的 schema**，注册表本身没动。模型如果还记得某个被裁掉的工具的名字，照样调得动。
9. **权限层判不了「合不合适」**：它判的是「这个工具在这个模式下、这条命令是否被允许」，不判「这个任务该不该用这个工具」。
10. **参数不做 schema 级校验**：schema 只是发给模型的说明，执行前不按它校验；类型不对由工具自己抛，被兜成错误文本。
11. **`TRIM_ORDER` 是写死的**：不按任务类型裁——一个读代码的任务和一个大改的任务，裁掉的工具是一样的。
