# 专题：上下文管理与压缩

> 这份专题展开 [coderagent-answers.md](coderagent-answers.md) 的 a1–a4 与 b9–b10：coder agent 怎么管上下文、
> 怎么压缩、**怎么尽量不丢东西**，以及**一次工具调用是怎么落进上下文、再回到模型手里的**。
>
> 相关代码：
> `src/coderagent/core/{context,summarize,budget,tokens,history,instructions,memory}.py`、
> `src/coderagent/tools/{executor,registry,permissions}.py`、
> `src/coderagent/config/schema.py`（`ContextConfig`）、`src/coderagent/run.py`（装配）。
> 单测：`tests/coderagent/core/`、`tests/coderagent/tools/`。

---

## 1. 一句话概括

> **上下文不是攒出来的，是每次现算出来的；被压缩掉的内容不是被删除了，是被移出了窗口。**

这两句话决定了后面所有的设计：

- 「现算」→ 权限模式、todo、指令、记忆都**不进历史**，每轮重算，不会把历史撑爆，也不会变成过期信息；
- 「移出窗口」→ 原文永远在事件日志里，压缩只是决定「这一轮给模型看多少」，不是决定「事实是否存在」。

---

## 2. 上下文的四层结构

`ContextEngine.build_messages()`（`core/context.py:145-168`）固定五段，顺序不可换：

| # | 段 | 角色 | 来源 | 会变吗 |
|---|---|---|---|---|
| 1 | system prompt | `system` | `agent.system_prompt` + skills / 子 agent 索引 | 启动时定 |
| 2 | 权限模式说明 | `user` | `tools/permissions.py` 的 `mode_block()` | **每轮重算** |
| 3 | 指令 + 记忆 + todo | `user` | `instructions.py` / `memory.py` / `session.metadata["todos"]` | 每轮重算 |
| 4 | 摘要 | `user` | `self.summaries` | 压缩时换 |
| 5 | 历史 | assistant / user / tool | `self.history.messages` | 追加 |

### 2.1 为什么第 2、3 段不进历史

**权限模式说明**：权限模式会在会话中途变（`/mode`、`/plan` 原地改 `policy.mode`）。如果烤进 system prompt，
模型看到的就是过期规则。早期版本的 `plan` 和 `readonly` 就是这么成了空壳——模式对模型完全不可见，
于是「不能写文件」这件事没人告诉模型。所以这段是**每次组装消息时现算**的（`_mode_text()`，`context.py:162-168`）。

**指令 / 记忆 / todo**：它们的性质是「本轮的外部状态」，不是「对话历史」。合并成**一条** user 消息
（`_instruction_text()`，`context.py:174-188`），而不是拆成几条——拆开会让模型误以为用户连着说了好几句话。
todo 渲染成 `<current_todos>` 复选框块：

```
<current_todos>
- [x] 读一下 calc.py
- [ ] 改掉 off-by-one
</current_todos>
```

### 2.2 子目录指令：惰性加载

`load_instructions(cwd, user_home)` 在启动时加载三处：用户 `CLAUDE.md` → 项目 `AGENTS.md` → 项目 `CLAUDE.md`。

**子目录的 `AGENTS.md` 不预读**。`ContextEngine.note_path(path)`（`context.py:345-357`）在 agent **碰到某个路径时**
才去 `cwd` 与该路径之间逐层加载（由深到浅，只认 `AGENTS.md`），加载过的按路径去重。
`ToolExecutor` 对每个带 `path` 参数的工具调 `on_path`（`run.py` 里接的就是 `context.note_path`）。

**为什么**：一个仓库可能有几百个目录的规矩文件，全量塞进上下文必炸。惰性加载让「我要去那个目录了」
和「我读到了那个目录的规矩」几乎同时发生。

---

## 3. 预算怎么算

`core/budget.py`：

```python
MODEL_CONTEXT_WINDOWS = {"gpt-": 128000, "claude": 200000, "deepseek": 64000, "qwen": 32768,
                          "llama": 8192, "gemini": 1000000, "mistral": 32768, "kimi": 262144,
                          "minimax": 204800}

def context_window_for(model_name, default=200000): ...   # 按模型名（去掉厂商前缀后）的前缀查表

limit          = max(0, context_window - reserved_output)
should_compact = estimated > min(int(context_window * compact_threshold), limit())
```

三条要点：

1. **窗口大小跟随模型，但显式配置优先**。`run.py` 的 `_context_config()`（`run.py:78-82`）检查
   `"context_window" in config.context.model_fields_set`——用户配了就用用户的，没配才查表。
2. **两个阈值取小的**：比例阈值（`compact_threshold`，默认 0.8）和绝对上限（`limit()`）谁紧听谁。
   这样小窗口模型不会被比例阈值放行到超限，大窗口模型不会因为比例太低而提前压缩。
3. **`reserved_output`（默认 8000）** 给模型的输出留位置——上下文不能占满整个窗口。

### 3.1 token 估算

`core/tokens.py` 的 `estimate_tokens(messages, tools)`（`tokens.py:40-52`）：

- 装了 `tiktoken` 就精确算：`MESSAGE_OVERHEAD(4) + len(encoding.encode(message_text(m)))`，
  外加工具 schema 的 JSON 长度（`tokens.py:40-52`）；
- 没有就退回启发式：`字符数 / 3.6 + 4 × 消息数`。

`message_text()` 把消息的 `content` 和每个 tool call 的 `name` + `arguments` 都算进去——
**工具调用的参数也是 token**，只算 content 会低估不少。

`tiktoken` 是懒加载且容错的：装不上、或者首次下载词表失败，都安静地退回启发式（`tokens.py:20-28`）。
估算只用来决定「要不要压」，不用来计费——**API 才是最后裁判**。

### 3.2 配置项

`ContextConfig`（`config/schema.py:83-94`）：

| 键 | 默认 | 含义 |
|---|---|---|
| `context.context_window` | 200000 | 窗口大小（不配则跟随模型名） |
| `context.reserved_output` | 8000 | 给输出留的 token |
| `context.compact_threshold` | 0.8 | 触发压缩的比例阈值 |
| `context.keep_recent_turns` | 20 | 至少保留最近多少轮 |
| `context.keep_recent_token_ratio` | 0.4 | 至少保留多少比例的窗口 |
| `context.compact_every_turns` | 40 | 最多隔多少轮强制压一次 |
| `context.auto_compact` | true | 关掉就完全不自动压缩 |
| `context.summarize_model` | "" | 用单独的模型做摘要；空 = 走路由的 `summarize` 用途 |
| `context.summary_chunk_tokens` | 0 | 一次摘要提示词能占多少 token；0 = 按摘要模型的窗口算 |

摘要模型可以是**另一个模型**（`run.py:161-164`）：配了就用它，没配就用路由里的 `summarize` 用途。
摘要跑在别的模型上时，它的成本会**记到主模型账上**（`context.py:225-228`），所以总账不错。

---

## 4. 压缩：触发、切点、摘要

### 4.1 三个触发口子

`ContextEngine.maybe_compact()`（`context.py:200-211`），每轮问模型之前调一次：

1. **预算到了**：`guard.should_compact(estimated_tokens())`；
2. **轮数到了**：`session.turn_count - last_compact_turn > compact_every_turns`；
3. **provider 报溢出**：`force_compact()`（`context.py:213-215`）——
   `loop.py` 的 `_query` 捕获上下文溢出异常后强制压一次，**然后重试一次**；压不动才返回错误
   （文本里带 "nothing left to compact"）。

第 3 条是兜底：前两条是**预判**，第 3 条是**事后救**。

**注意**：`auto_compact` 关掉时，`maybe_compact()` 第一行就返回 `False`（`context.py:202`），
所以第 2 条**永远不会单独成立**——「只按轮数压」是做不到的，`auto_compact` 是总开关
（只有第 3 条的 `force_compact()` 不受它管）。

### 4.2 切点：永远在轮边界

`History.turn_starts()`（`core/history.py:27-29`）= 所有 `role == "user"` 的消息下标——**轮的唯一定义**。
一轮 = 一条 user 消息 + 模型为它做的一切（assistant 消息 + 后续工具结果）。

切在轮边界上，工具结果才不会跟「发起它的那条 assistant 消息」分家。切在半路，模型会看到
「请求还在，结果没了」。

### 4.3 切点：两条规则取更严的

`_cut_index()`（`context.py:252-278`）：

```
earliest = starts[max(0, len(starts) - keep_recent_turns)]     # 最近 N 轮的起点
budget   = int(context_window * keep_recent_token_ratio)       # 保留的 token 份额
cut = earliest
for index in 候选轮边界:
    if index <= earliest and estimate_tokens(messages[index:]) >= budget:
        cut = index                                            # 往前切到 token 份额满足为止
```

也就是说：**保留量取「最近 N 轮」和「最近 40% 窗口 token」里更靠前的那个**。
两者取大，保证「几轮特别大的对话」和「很多轮小对话」都能留下足够内容。

最后还有一条**硬上限**兜底：

```
limit = guard.limit() - estimate_tokens(摘要本身)
while estimate_tokens(messages[cut:]) > limit:
    cut = 下一个轮边界
```

即「留下的原文 + 摘要」也不能超预算。宁可多切一轮，也不能让这一次请求直接被 provider 拒掉。

### 4.4 摘要：固定 schema，不是自由文本

`core/summarize.py` 的 `FIELDS`：

```json
{
  "goal": "用户想达成什么，一句话",
  "findings": ["确认过的事实，来自代码时带上 file:line"],
  "decisions": ["做了哪些技术决定，为什么"],
  "files_touched": [{"path": "src/cache.py", "change": "改了什么", "state": "modified"}],
  "open_questions": ["还没解决的问题"],
  "next_steps": ["具体下一步"],
  "errors_seen": ["撞过什么错，怎么解决的"]
}
```

`parse_summary()`（`summarize.py:115-130`）容错：剥 ```json 围栏 → 取第一个 `{` 到最后一个 `}` → `json.loads`；
不是 dict 就返回 `None`（判失败）。

渲染成 `<session_summary>` 块（`summarize.py:87-113`），**放在历史之前**——被摘要的是更早的那部分。

**为什么是结构化字段而不是散文**：模型要记住「还剩什么没做完」，靠 JSON 字段比靠一段话稳得多。

### 4.5 摘要分块：历史装不下一个提示词的时候

被压缩掉的那段历史可能**比一次提示词还大**。旧的做法是把它整个塞进一次调用：
超了 → provider 溢出 → 重试一次 → 还是超 → 只剩最后 5 条消息活着，其余静默蒸发。

现在按 **map-reduce** 做（`core/summarize.py` 的 `chunk_messages()` + `merge_prompt()`，
`core/context.py:284-306` 的 `_summarize()`）：

```
被压缩的历史
   │
   ├─ chunk_messages(messages, limit)   按轮切成若干块（轮不拆；单轮超大才在消息边界拆）
   │
   ├─ 每块一次 summarize_prompt  →  若干份 partial summary
   │
   └─ 一次 merge_prompt(parts, previous)  →  一份 summary（previous = 上一轮的摘要）
```

- **单块时走老路径**：不额外调用，不额外花钱，行为与从前完全一致。
- **合并失败也不丢东西**：`merge_summaries()`（纯代码，不调模型）把若干份 partial 拼起来——
  goal 取最后一份非空的，列表去重拼接，`files_touched` 按 path 去重（后者覆盖前者）。
  结果比模型合并啰嗦，但**一条都不丢**。
- **上一份摘要进合并提示词**：第二次压缩不会丢第一次的结论（见 §5.4）。

块的大小由 `context.summary_chunk_tokens` 决定；为 0 时按摘要模型的窗口算
（`window - reserved_output - 2000`，`context.py:320-328`）。

**为什么值得多花一次模型调用**：一次超长的提示词失败，是**整段历史**的损失；
分块之后失败只影响一块，而且还能机械兜底。

---

## 5. 完整性：六道保真机制

压缩天然有损——摘要是一次转述。coder agent 的做法不是指望模型「转述得好」，
而是**在代码里把丢内容的路径一条条堵死**。

### 5.1 压缩是「移出窗口」，不是「删除事实」

被切掉的原文**永远在事件日志里**（JSONL 追加写，`core/session.py`）。
`COMPACTION` 事件记下切了多少条、多大、多贵、摘要全文（`context.py:217-248`）：

```json
{"compacted_messages": 42, "tokens": 18342, "summary_tokens": 1204,
 "summary_ratio": 0.0656, "cost": 0.012,
 "summary": {...}, "summaries": [{...}]}
```

`summary_ratio` = 摘要多大 / 被替换掉的那段原文多大。**这个比值是摘要质量的仪表盘**：
它突然变大，要么是摘要变啰嗦了，要么是被摘的那段变啰嗦了。
`telemetry.collect()` 把它收进 `Metrics.summary_ratios`，
评测报告里给出均值和最差值（`eval/report.py`）。

`restore()` 重放日志时按 `compacted_messages` 截断（`context.py:99-101`），原文随时能取回。

**「模型看不见」和「事实没了」是两回事**——这是整套设计的地基。

### 5.2 切点必在轮边界

见 §4.2。工具结果与它的请求不分家。

### 5.3 摘要失败不许通过

`_summarize()`（`context.py:284-306`）的判定链（重试的循环在 `_ask()`，`context.py:308-318`）：

```
for _ in range(2):                      # 最多两次
    text = summary_model.complete(...)   # 抛异常就 continue
    summary = parse_summary(text)
    if summary is not None and (summary.files_touched or not expect_files):
        break                           # 过了
    summary = None                      # 没过
if summary is None:
    summary = conservative_summary(payload)
```

`expect_files` = 被压缩的部分里有没有 `write` / `edit` / `multi_edit`（`context.py:359-365`）。

**关键判定**：压缩掉的段落里有写操作，但摘要的 `files_touched` 是空的 → **算失败**。
模型没交代它改过文件，说明它没读懂被压缩的内容。这时不能接受，重试一次。

两次都失败才用 `conservative_summary()` 兜底（`summarize.py:257-269`）：

```python
Summary(
    goal="the earlier part of the conversation was compacted",
    findings=[最后 5 条消息，每条截 400 字],
    next_steps=["re-read the files that were mentioned to recover the details"],
)
```

**宁可给模型一句笨话，也不要假装压缩成功了。**

### 5.4 摘要链不断

`summaries` **永远只有一份**——`self.summaries = [summary]`（`context.py:229`）是**替换**不是追加。
否则摘要会越堆越多把预算吃光（第二份摘要的输入里已经有第一份，再加一份就是复利）。

但压缩第 N 次时，**上一份摘要会作为额外输入喂给模型**（`context.py:291`）：

```python
previous = self.summaries[-1] if self.summaries else None
# 单块：作为一条 user 消息接在历史后面
# 多块：作为 merge_prompt 的 previous 参数
```

所以第二次压缩之后，第一次的结论还在——只是被合并进了新摘要。**摘要会被压缩，但不会被遗忘。**

### 5.5 关键信息不问模型

`recent_errors` 是**从消息里直接算**的（`summarize.py:271-278`）：

```python
for message in messages:
    if message.get("role") == "tool" and content.startswith("Error:"):
        errors.append(content[:300])
summary.recent_errors = errors[-3:]
```

不问模型。**模型忘了报错，不等于错误消失。** 这条派生字段不受模型输出质量影响。

### 5.6 工具输出被裁剪时保留头尾

`trim_text` / `trim_lines`（`tokens.py:66-118`）：保留头 40% + 尾 40%，中间写明省略了多少：

```
... [120 lines, 980 tokens elided, use grep/offset to view that region] ...
```

**告诉模型怎么把内容找回来**，而不是默默截断。`trim_lines` 还额外返回 `start_line` / `end_line` / `head_lines`，
让调用方把行号对上——否则裁剪之后模型看到的行号全是错的。

---

## 6. 一次工具调用，怎么进上下文又回到模型手里

工具调用是上下文里**增长最快**的东西：一轮里可能有十几次调用，每次的 observation 都进历史，
都可能把预算撑爆。所以「调用怎么落地」不只是工具层的事，也是上下文的事。

### 6.1 六步，其中四步在执行之前

```
模型返回 tool_calls
   │
   ├─ 1. plan()        规整参数：不是合法 JSON / 不是对象 → 记 error，不往下走
   │
   ├─ 2. TOOL_CALL 事件  ← 在执行之前记账：模型「打算做什么」
   │
   ├─ 3. _prepare()    查注册表 → PreToolUse hook → 权限判定 → 审批
   │                   （被拒的 action 不执行）
   │
   ├─ 4. _run()        on_path（捡起目录指令）→ before_write（checkpoint）→ 执行
   │
   ├─ 5. TOOL_RESULT 事件（含 diff）
   │
   └─ 6. observation   {"role": "tool", "tool_call_id": ..., "content": ...}
                        └─ 进历史，成为下一轮上下文的一部分
```

关键的两点：

- **第 2 步在第 4 步之前**：「模型想干什么」永远早于「它干了什么」被记下来。事后复盘时能看出
  一次失败的调用**本来**是想改哪个文件。
- **第 3 步在第 4 步之前**：权限和 hook 判定的是**最终会执行的那份参数**（hook 改写后的），
  被拒的工具**不会真的动过文件**。

### 6.2 观察结果永远是模型能读的消息

observation 有两种，内容不同但形状一样（都带 `tool_call_id`，模型才能对上号）：

- **成功**：工具的输出，可能被裁剪过（`trim_text` / `trim_lines`，见 §5.6）；
- **失败**：一段 `Error: ...` 文本——工具抛异常、参数不是合法 JSON、工具自己不存在的、权限被拒的，
  全都走这一条路。

失败**不中断整轮**。模型下一轮看到的是一条普通的 tool result，只是内容在说「哪里错了」。
这就是为什么 `recent_errors`（§5.5）只要扫 `role == "tool"` 且内容以 `Error:` 开头就能拿到错误——
**错误在上下文里是有形状的**，不靠模型转述。

### 6.3 上下文里能看见「越界的东西」

模型偶尔会调一个不存在的工具（`Error: unknown tool 'xxx'. Available tools: ...`），
或者调一个被权限挡下的工具（`Error: permission denied for 'xxx'. ...`）。
这些文本都在历史里，所以复盘时能直接看出模型「在乱试什么」。

评测报告里的 `tool_errors` 数的就是它们（`eval/runner.py:353`）。
再往上一层，`require_tools` 要求某些任务**必须**用某个工具改某个文件——
用 shell 绕过去不算完成；`no-op` 任务反过来测「不该改的时候别改」。

### 6.4 两条要留意的边界

1. **被裁掉的工具仍然能执行**。`registry.schemas()` 裁的是**发给模型的 schema**，注册表本身没动。
   模型如果还记得某个被裁掉的工具的名字，照样调得动——裁剪省的是上下文，不是权限。
2. **参数不做 schema 级校验**。schema 只是发给模型的说明；执行前不按它校验，类型不对由工具自己抛，
   被兜成 `Error:` 文本。

---

## 7. 压缩之外：还有什么在省 token

压缩是最后手段，前面还有几层：

| 手段 | 在哪 | 效果 |
|---|---|---|
| 指令不进历史 | `context.py:174-188` | 每次重算，不累积在 history 里 |
| 子目录指令惰性加载 | `context.py:345-357` | 只加载走过的目录 |
| 工具 schema 预算裁剪 | `tools/registry.py` | schema 占窗口的 10%，超了按 `TRIM_ORDER` 丢 |
| 工具输出裁剪 | `core/tokens.py` | 头尾保留，中间标出来 |
| 工具输出上限 | `tools/builtin/` | `read` 2000 行、`glob` 200 条、`grep` 100 行、`bash` 按 `max_output_tokens` |
| 上下文窗口跟随模型 | `run.py:78-82` | 小模型用小窗口，不按 200k 装 |

---

## 8. 边界与已知瑕疵

说清楚比藏着好：

1. **摘要天然有损**。它是模型的二次转述。保真靠的是「固定 schema + 失败校验 + 兜底」，不是靠模型自觉。
2. **摘要永远只有一份**。第二次压缩时，第一次摘要的细节被压成一句再合并进新摘要。
3. **窗口外的内容模型取不回**。原文在磁盘上，但模型只能靠 `read` / `grep` 重新捞——这就是
   `conservative_summary` 要写「去重读文件」的原因。
4. **`_cut_index` 用的是 `config.context_window` 而不是 `guard.limit()`**（`context.py:252` vs `budget.py:35`），
   两者差一个 `reserved_output`，极端情况下会切得偏保守。
5. **指令块会累积**。`instruction_blocks` 随 agent 走过的目录增长，且**不随压缩清理**。
6. **相邻的两条 user 消息**。权限模式说明和摘要是两条连续的 `user` 消息，中间没有 assistant。
   合法，但严格说不是自然对话形态。
7. **压缩的切点不记「为什么」**。`COMPACTION` 事件记了切了多少条和摘要，但没记触发原因
   （预算到了 / 轮数到了 / provider 溢出）。要区分得看日志上下文。
8. **合并比合并前的摘要更容易丢细节**。分块之后多了一次「partial → 一份」的重述，
   这一层同样是模型的二次转述。机械兜底（`merge_summaries`）不丢，但更啰嗦。
9. **摘要质量的度量只有一个比值**。`summary_ratio` 能看出摘要变大了，
   但看不出它变**大得对不对**——一份啰嗦但完整的摘要和一个丢了一半的摘要，比值可能一样。
10. **被裁掉的工具仍然能执行**。schema 裁剪省的是上下文，不是权限（见 §6.4）。
11. **参数不做 schema 级校验**。schema 只是发给模型的说明，错了由工具自己抛（见 §6.4）。

---

## 9. 一张图

```
                    ┌──────────────── 事件日志（JSONL，唯一事实来源）──────────────┐
                    │  USER_MESSAGE / ASSISTANT_MESSAGE / TOOL_RESULT / COMPACTION │◀── 原文永远在这
                    └──────────────────────────────────────────────────────────────┘
                                              │ 重放
                                              ▼
  system ─▶ 权限模式 ─▶ 指令+记忆+todo ─▶ <session_summary> ─▶ history ─▶ 模型
              (每轮现算)   (每轮现算)         (压缩掉的那部分)     (原文)
                                                │
                          预算到了 / 轮数到了 / provider 溢出
                                                │
                                                ▼
                              _cut_index() 切在轮边界，两规则取严
                                                │
                                                ▼
                     _summarize()：装不下就分块，每块一份 partial
                                                │
                                                ▼
                        merge_prompt() 把 partial 合成一份（带上一份摘要）
                                                │
                                                ▼
                        COMPACTION 事件（切了多少 / 多大 / 多贵 / 摘要全文 / 比值）

  工具调用这一圈（在 history 内部发生，observation 也进 history）：

  模型返回 tool_calls ─▶ plan() 规整 ─▶ TOOL_CALL 事件 ─▶ _prepare()
  （查表 / hook / 权限 / 审批，都在执行之前）                        │
                                                                   ▼
                              _run() 执行 ─▶ TOOL_RESULT 事件 ─▶ observation
                                                                   │
                              失败也是一条 "Error: ..." 的 observation ──▶ 回模型
```

---

## 10. 延伸阅读

- [coderagent-answers.md](coderagent-answers.md) 的 a1–a4 与 b9–b10：逐题作答（本专题的浓缩版）。
- [coderagent-design-logic.md](coderagent-design-logic.md)：为什么这么设计（承重决策与不变量）。
- [milestones/M2-context-session.md](milestones/M2-context-session.md)：M2 阶段的原始设计与验收。
- [coderagent-eval.md](../usage/coderagent_eval.md)：评测里怎么隔离上下文（`MSWEA_CODER_HOME`）。
