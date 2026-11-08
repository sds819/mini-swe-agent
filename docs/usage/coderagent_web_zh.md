# 网页版

`coder web` 在浏览器里跑同一个 agent。聊天页是终端界面的窗口版，设置页把模型参数配成表单——
这两件事在文本编辑器里最烦人。

> 英文版：[The web interface](coderagent_web.md)

- [安装与启动](#install)
- [命令行选项](#cli)
- [聊天页](#chat)
- [设置页](#settings)
- [审批](#approvals)
- [当 API 用](#api)
- [安全模型](#security)
- [和终端的差别](#differences)
- [常见问题](#faq)

## 安装与启动 {#install}

```bash
pip install -e ".[web]"      # fastapi、uvicorn、jinja2
cd my-project
coder web
```

终端会打印它监听的地址：

```
coder web: http://127.0.0.1:8765
```

浏览器打开这个地址就能用。服务一直开着，按 `ctrl+c` 停掉。

## 命令行选项 {#cli}

| 选项 | 作用 |
|---|---|
| `--cwd` | agent 工作的目录。浏览器里看到的一切都在它里面（默认当前目录） |
| `--host` | 监听地址，默认 `127.0.0.1` |
| `--port` | 端口，默认 `8765` |
| `--model` / `-m` | 这一轮用的模型 |
| `--config` / `-c` | 配置文件，或者 `key=value` 覆盖 |
| `--permission-mode` | `default` / `acceptEdits` / `plan` / `bypass` / `readonly` |

```bash
coder web --cwd ~/projects/my-app --port 8080 -m deepseek/deepseek-flash
```

## 聊天页 {#chat}

打开 `http://127.0.0.1:8765/`。三栏：

- **左栏**：这个目录的会话列表，和工作目录的文件树。`New session` 开一个新会话，
  点列表里的会话切换过去。
- **中栏**：对话。消息是气泡，工具调用是卡片（带输出和这次改动的 diff），审批是带三个
  按钮的卡片。下面的输入框既能发消息也能发 slash 命令（`/help`、`/clear`、`/cost`……，
  和终端里是同一套命令，列表在输入框右边的下拉框里）。`Interrupt` 停掉正在跑的那一轮。
- **右栏**：状态（模型、上下文用量、这一轮花了多少、权限模式、会话状态）、这一轮改过的
  文件和它们的 diff、正在看的那个文件的内容。

模型回答是**边生成边显示**的。断线重连会接着上次的位置继续，不会从头再来。

一轮结束时会话会在记忆里沉淀一下（见[记忆](coderagent_memory.md)），对话里出现一条
细的分隔线，标着这次花了多少钱。

流式输出的碎片只推给正在看的浏览器，不留在会话的缓存里——所以长回答不会把历史挤掉。
中途才打开页面的浏览器看到的是整段回答。

## 设置页 {#settings}

打开 `/settings`，把模型配置写成表单：

| 字段 | 落到哪 |
|---|---|
| Model name | `model.model_name`，比如 `deepseek/deepseek-flash` |
| API base | `model.model_kwargs.api_base`——第三方模型的地址 |
| API key | `model.model_kwargs.api_key`。**只写不读**，浏览器永远拿不到明文 |
| Max retries | `model.max_retries` |
| Cache control | `model.set_cache_control`（`ephemeral` 或空） |
| Routing | `model.routing`，一行一个 `用途: 模型` |
| Routing rules | `model.routing_rules`，一行一个 `when: purpose` |
| Extra parameters | `model.model_kwargs` 的其余部分（YAML，原样传给厂商） |

每个字段下面写着它来自哪一层：`defaults`、`project`、`user` 或 `env`。页面底部的表格列出
所有层，含密钥的项都被抹成 `***`。

`Test the connection` 用表单里的设置发一次最便宜的调用，测通了再 `Save`。

三件要记住的事：

- **只写用户级文件** `~/.coderagent/config.yaml`（或者 `$MSWEA_CODER_HOME/config.yaml`）。
  项目级的 `.coderagent/config.yaml` **永远不写**——它会进 git。文件里页面不认识的段落原样保留。
- **对新会话生效**。跑着的服务保留启动时的配置，新会话建 loop 时重新读一遍文件。
  当前这个会话想立刻换模型，用 `/model <名字>`。
- **环境变量里的 key 在页面上看不到**。页面读的是配置文件，而 `DEEPSEEK_API_KEY` 这类变量
  在环境里，所以 `api_key_set` 会是 false——这是正常的，页面管的是配置文件里的 key。

## 审批 {#approvals}

agent 要跑命令、写文件时会问。卡片上有三个按钮：

- **Allow**——这次执行。
- **Deny**——不执行，理由回给模型，模型会换个做法，而不是硬来。
- **Always allow**——这次执行，**并且往 `~/.coderagent/rules.yaml` 写一条规则**，
  以后这个工具都放行。按钮上写明了这一点。

没人回答就是拒绝（`ui.approval_timeout` 秒，默认 5 分钟）。被拒的工具不会执行。

## 当 API 用 {#api}

页面做的每个动作都是普通 HTTP 调用，可以拿脚本驱动。交互式文档在 `/api/docs`。

写接口（发消息、审批、中断、写配置）要带一个头 `X-Coder-Client: 1`。浏览器从别的网站
发这个头要先过预检，而服务端不给预检许可，所以别的网站没法驱动你的 agent。`curl` 不受影响。

```bash
# 建一个会话
curl -X POST http://127.0.0.1:8765/api/sessions -H "X-Coder-Client: 1"
# => {"id":"20261108-382ff4","cwd":"/path/to/project"}

# 发一句话
curl -X POST http://127.0.0.1:8765/api/sessions/20261108-382ff4/messages \
  -H "X-Coder-Client: 1" -H "Content-Type: application/json" \
  -d '{"text": "fix the failing test"}'

# 看它干了什么（事件流）
curl -N "http://127.0.0.1:8765/api/sessions/20261108-382ff4/stream?since=0"
```

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/sessions` | 这个目录的会话 |
| POST | `/api/sessions` | 新建会话 |
| GET | `/api/sessions/{id}` | 一个会话 |
| GET | `/api/sessions/{id}/events` | 整个会话，从日志读 |
| GET | `/api/sessions/{id}/items?since=` | 浏览器还没看到的条目 |
| GET | `/api/sessions/{id}/stream?since=` | 事件流（SSE） |
| GET | `/api/sessions/{id}/status` | 状态条的字段 |
| GET | `/api/sessions/{id}/metrics` | 这个会话花了多少 |
| GET | `/api/sessions/{id}/changes` | 这个会话改过的文件和 diff |
| POST | `/api/sessions/{id}/resume` | 续接日志里的会话 |
| POST | `/api/sessions/{id}/fork` | 复制一个会话 |
| POST | `/api/sessions/{id}/messages` | 发消息，或者跑 slash 命令 |
| POST | `/api/sessions/{id}/interrupt` | 停掉正在跑的那一轮 |
| POST | `/api/approvals/{id}` | 允许、拒绝、或者永久允许一个工具 |
| GET | `/api/commands` | 有哪些 slash 命令 |
| GET | `/api/config` | 模型配置，和每个字段来自哪一层 |
| PUT | `/api/config/model` | 把模型设置写进用户级文件 |
| POST | `/api/config/model/test` | 拿设置试一下 |
| GET | `/api/files?path=&depth=` | 一个目录里的条目 |
| GET | `/api/file?path=` | 一个文件的内容 |
| GET | `/api/diff?path=` | 工作区里这个文件的改动 |

状态码：正忙着在跑一轮时再发消息 → `409`；审批 id 不认识 → `404`；路径越界 → `403`；
空消息 → `400`。

## 安全模型 {#security}

放到网络上之前先看这一节。

- **没有认证**。能访问这个端口的人就能驱动 agent，而 agent 能在工作目录里跑 shell 命令。
  这是给「一个人、一台机器」用的工具，信任模型跟信任 `coder` 命令行一样。
- **默认只听 `127.0.0.1`**。`--host 0.0.0.0` 会打一条警告，然后服务给所有能连到这台
  机器的人用。
- **浏览器骗不到它**。写接口要一个跨站请求发不出来的头。
- **浏览器看不到工作目录外面**。每个路径都先 `resolve()`，再跟工作目录和
  `permissions.include_dirs` 比对；用户写的规则放宽不了这个边界。
- **API key 不出服务器**。设置页只拿到 `api_key_set` 和末四位；分层预览里所有密钥都被抹掉。
- **API key 只写用户级文件**，绝不写进会进 git 的项目级文件。

## 和终端的差别 {#differences}

| | 终端 | 浏览器 |
|---|---|---|
| 流式输出 | 有 | 有，走 SSE |
| 审批 | 有 | 有，同样三个答案 |
| slash 命令 | 有 | 有，同一套 |
| 模型配置 | 一个文本文件 | 一个表单，外加分层预览 |
| 项目文件 | agent 的工具 | 左边的文件树 |
| 花费 | `/cost` | 状态条，外加 `/cost` |

核心是同一套：同一批会话、同一份事件日志、同一批工具、同一套权限。浏览器里开的会话可以用
`coder --resume <id>` 在终端里接着聊，反过来也一样。

浏览器目前还没有的：终端能用方向键选审批答案，也能把长输出折叠起来；浏览器这边是全展开的。

## 常见问题 {#faq}

**「设置页里 `api_key_set` 是 false」**
key 在环境变量里（`DEEPSEEK_API_KEY` 之类），不在配置文件里。页面只管配置文件的 key，
模型本身照样能用环境变量里的 key。

**「改了设置没生效」**
对**新会话**生效。当前这个会话还在用启动时的配置，想立刻换就 `/model <名字>`。

**「写接口返回 403」**
少了 `X-Coder-Client: 1` 头。浏览器里不用管，页面自己会带。

**「发消息返回 409」**
这个会话正忙着在跑一轮。等它跑完，或者先 `Interrupt`。

**「读文件返回 403」**
路径在工作目录外面。要么改路径，要么在配置里加 `permissions.include_dirs`。

**「页面打开是空的 / 连不上」**
服务没起，或者端口不是 8765。终端里那行 `coder web: http://…` 就是地址。

**「回答怎么显示了两遍」**
这是老版本的前端问题，已经修了：流式气泡会被后面那条完整消息替换掉。

**「一轮结束后流断了」**
事件流一轮结束就关，浏览器拿新的 `since` 重开，中间不会漏内容。一轮里长时间不说话的
时候流是开着的，不会提前断。
