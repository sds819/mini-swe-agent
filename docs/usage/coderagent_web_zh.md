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

页面本身不滚动，每一栏各滚各的。对话区会跟着新的输出滚到底，除非你往上翻去看别的东西。
当前这一轮之前的历史折叠在顶部一个块里，点开就能看。
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
| Model name | `model.model_name`，比如 `deepseek/deepseek-flash`。名字前面那个厂商决定调谁：第三方端点写 `openai/MiniMax-M2.7`，DeepSeek 写 `deepseek/deepseek-flash` |
| Litellm config file | `model.litellm_config`——别名文件，模型名可以是里面的一条别名 |
| API base | `model.model_kwargs.api_base`——第三方模型的地址 |
| API key | `model.model_kwargs.api_key`。点一下显示，再点一下收起 |
| Max retries | `model.max_retries` |
| Cache control | `model.set_cache_control`（`ephemeral` 或空） |
| Routing | `model.routing`，一行一个 `用途: 模型` |
| Routing rules | `model.routing_rules`，一行一个 `when: purpose` |
| Extra parameters | `model.model_kwargs` 的其余部分（YAML，原样传给厂商） |

每个字段下面写着它来自哪一层：`defaults`、`project`、`user` 或 `env`。页面底部的表格列出
所有层，含密钥的项都被抹成 `***`。

`Test the connection` 用表单里的设置发一次最便宜的调用，测通了再 `Save`。

### 测一个模型 {#test-a-model}

还有一块独立的面板，不写任何文件，只管试：Endpoint、API Key、Model Name，
右边一个 `Test connection` 按钮——就是厂商后台给你表单的那个样子。

| 字段 | 意思 |
|---|---|
| Endpoint | 厂商的地址。可以直接粘完整的 `https://api.example.com/v1/chat/completions`：`/v1` 后面那段会被剪掉，因为 litellm 自己会加 |
| API Key | 这个地址的 key。点一下显示上面设置里的 key，再点一下收起来 |
| Model Name | 模型名。前面那个厂商决定调谁：`openai/MiniMax-M2.7`。没写就补 `openai/`——这个地址是 OpenAI 兼容的那种 |

地址或 key 留空，就用上面设置里的。结果和表单那边的测试一样，也是那几行。

三件要记住的事：

- **只写用户级文件** `~/.coderagent/config.yaml`（或者 `$MSWEA_CODER_HOME/config.yaml`）。
  项目级的 `.coderagent/config.yaml` **永远不写**——它会进 git。文件里页面不认识的段落原样保留。
- **对新会话生效**。跑着的服务保留启动时的配置，新会话建 loop 时重新读一遍文件。
  当前这个会话想立刻换模型，用 `/model <名字>`。
- **环境变量里的 key 在页面上看不到**。页面读的是配置文件，而 `DEEPSEEK_API_KEY` 这类变量
  在环境里，所以 `api_key_set` 会是 false——这是正常的，页面管的是配置文件里的 key。
- **key 那一栏**。平时只显示 `set (********1234)`，明文不露。点一下输入框，服务器
  才把 key 发过来显示；再点一下收起来。别名文件里的 key 也算数：key 在 litellm
  配置里，显示的就是它。输入框留空表示保留原来的 key——只有框里有东西才会写进去。

## 权限 {#permissions}

权限有两个地方管，管的不是同一件事：

| 在哪 | 改什么 | 什么时候生效 |
|---|---|---|
| 设置页（`/settings`） | 用户级配置文件里的 `permissions:` 段 | **下一个**会话 |
| 聊天页（`/`） | 当前这个会话的权限模式 | **立刻** |

### 五个模式

| 模式 | 意思 |
|---|---|
| `default` | 凡是会改东西的工具都要审批 |
| `acceptEdits` | 写操作直接放行，其余的还是要问 |
| `plan` | 只读：agent 只看不改，把计划写出来 |
| `readonly` | 只读：agent 只看不改，把看到的说出来 |
| `bypass` | 一律不问，所有工具调用都放行——无人值守跑的时候用 |

`plan` 和 `readonly` 会拒掉所有会改东西的工具（`bash` 也算），而且模型会被告知这件事，
所以它会说出看到的东西，而不是动手去改。

### 设置页

表单里有模式、禁止访问的路径、额外的目录，写到和模型同一个用户级文件
`~/.coderagent/config.yaml`（或者 `$MSWEA_CODER_HOME/config.yaml`）。项目级的文件永远不写，
`permissions.rules` 里的规则也不动——那些是审批卡片上 `Always allow` 按钮的事。

和模型一样，**对新会话生效**：跑着的会话还是它原来的模式。

### 聊天页

右栏顶上有一个模式下拉框。改一下就把当前会话的模式换掉，不用重启任何东西：策略是原地改的，
所以下一个工具调用就能看到，模型也会在下次组装上下文时知道。这就是无人值守跑法最省事的地方——
跑测试前拨到 `bypass`，跑完拨回 `default`。

### 服务端启动时钉死的模式

`coder web --permission-mode bypass` 会把模式钉死：它盖过配置文件，因为策略是按
`permission_mode or config.permissions.mode` 建的。服务端是带模式启动的，设置页会明说，
不会让你以为改了文件就生效了。

钉死的是会话**开始时**的模式，不是锁：聊天页照样能换当前会话的模式——那是你当着会话的面
做的决定，不是文件里的一个设置。

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
| POST | `/api/sessions/{id}/mode` | 换掉这个会话的权限模式 |
| POST | `/api/approvals/{id}` | 允许、拒绝、或者永久允许一个工具 |
| GET | `/api/commands` | 有哪些 slash 命令 |
| GET | `/api/config` | 模型配置，和每个字段来自哪一层 |
| GET | `/api/config/model/key` | 模型的 key，明文 |
| GET | `/lang/{language}` | 换个语言，记在 cookie 里 |
| PUT | `/api/config/model` | 把模型设置写进用户级文件 |
| PUT | `/api/config/permissions` | 把权限设置写进用户级文件 |
| POST | `/api/config/model/test` | 拿设置试一下 |
| GET | `/api/files?path=&depth=` | 一个目录里的条目 |
| GET | `/api/file?path=` | 一个文件的内容 |
| GET | `/api/diff?path=` | 工作区里这个文件的改动 |

状态码：正忙着在跑一轮时再发消息 → `409`；审批 id 不认识 → `404`；路径越界 → `403`；
空消息 → `400`；权限模式不认识 → `400`。

## 页面的语言 {#language}

页面给中文地区（大陆、香港、澳门、台湾）的人看是中文，其它地方是英文。
决定的是访客所在的地方。

| 地区从哪来 | 怎么来的 |
|---|---|
| 服务端前面的代理 | 代理写的那个头：`CF-IPCountry`、`X-AppEngine-Country`、`X-Vercel-IP-Country`、`X-Country-Code` |
| geoip 数据库 | `~/.coderagent/GeoLite2-Country.mmdb`（或者 `CODERAGENT_GEOIP_DB` 指的那个路径）。要装 `geoip2` 这个包，agent 本身不依赖它 |
| 浏览器 | 地区不知道的时候，看 `accept-language` |

访客自己说了算：顶栏那个下拉框换语言，换完记在 cookie 里；
每个页面也都可以加 `?lang=zh`（或者 `?lang=en`）。

### 加一种语言

加语言要动三个地方：

1. `src/coderagent/web/templates/<代码>/`——把 `en/` 目录复制一份，翻译里面的文字。
   一共四个文件：`base.html`、`chat.html`、`settings.html`、`macros.html`。
2. `src/coderagent/web/i18n.py`——`LANGUAGES` 里加一条（代码、用该语言写的语言名、
   用英文写的语言名），`STRINGS` 里加上浏览器要的文案。
3. `src/coderagent/web/i18n.py`——`REGION_LANGUAGES` 里写上这个语言对应的地区，
   那些地方的访客不用问就能拿到。

没有模板的语言不会被提供：顶栏的下拉框只列能上的语言，上不了的语言退回英文。

`STRINGS` 里是浏览器运行时才显示的文案（按钮上的字、状态栏的标签）。
页面本身的文字在模板里。

## 安全模型 {#security}

放到网络上之前先看这一节。

- **没有认证**。能访问这个端口的人就能驱动 agent，而 agent 能在工作目录里跑 shell 命令。
  这是给「一个人、一台机器」用的工具，信任模型跟信任 `coder` 命令行一样。
- **默认只听 `127.0.0.1`**。`--host 0.0.0.0` 会打一条警告，然后服务给所有能连到这台
  机器的人用。
- **浏览器骗不到它**。写接口要一个跨站请求发不出来的头。
- **浏览器看不到工作目录外面**。每个路径都先 `resolve()`，再跟工作目录和
  `permissions.include_dirs` 比对；用户写的规则放宽不了这个边界。
- **key 只在你要的时候才露面**。设置页平时只拿到 `api_key_set` 和末四位；分层预览里所有密钥
  都被抹掉。点一下 key 那一栏，服务器才把明文发过来；这个请求要带客户端那个头，所以
  别的站点的页面问不到它。
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

**「启动时报 address already in use」**
端口被别的程序占了（常见是上一个没关掉的 `coder web`）。换一个：`--port 8766`。

**「回答怎么显示了两遍」**
这是老版本的前端问题，已经修了：流式气泡会被后面那条完整消息替换掉。

**「一轮结束后流断了」**
事件流一轮结束就关，浏览器拿新的 `since` 重开，中间不会漏内容。一轮里长时间不说话的
时候流是开着的，不会提前断。
