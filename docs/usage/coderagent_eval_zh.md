# 评测（eval）

coding agent 本身就是一套 harness：事件溯源、权限层、结构化工具、上下文治理、可观测性。
一套从来没有被测量过的 harness，就是一套从来没有被改进过的 harness。
`coder eval` 跑一批任务，把 agent 干了什么报出来，这样 harness 的每一次改动都能和上一次的对比。

```bash
coder eval evals/basic --format json --out /tmp/eval.json
```

## 任务集（suite）

一个 suite 是一个目录，里面每个子目录是一个任务。任务目录里有 `task.yaml`，
其余文件（除 `*.yaml`/`*.yml` 外）是 fixture：agent 开始前会被复制进工作目录。

```yaml
# evals/basic/off-by-one/task.yaml
id: off-by-one                # 可选，默认取目录名
prompt: |                     # 或者 `prompts:`，一个列表：每个 prompt 一轮
  calc.py 里的 add_one 差一。修好它，让测试通过。
setup:                        # 可选，在 agent 开始前于工作目录执行
  - pip install -e .
verify:                       # 必填，在 agent 结束后执行；全部 exit 0 才算通过
  - python -m pytest -q tests/test_calc.py
timeout: 300                  # 可选，agent 这一轮的墙钟秒数（默认 300）
verify_timeout: 300           # 可选，每条 verify 命令的秒数（默认 300）
expect: pass                  # 可选，`pass`（默认）或 `fail`
tags: [bugfix]                # 可选
require_tools:               # 可选，这个任务需要的工具，以及它们必须改的文件
  - tools: [edit, multi_edit]
    paths: [calc.py]
config:                       # 可选，配置覆盖：YAML 文件路径或 `a.b=c`
  - permissions.yaml          # task.yaml 旁边的 YAML 文件
  - agent.max_turns=20
script:                       # 可选，脚本化模型；为空 = 用真实模型
  - content: 先看一下文件。
    tool_calls:
      - tool: read
        args: {path: calc.py}
  - content: 找到 bug 了，改掉。
    tool_calls:
      - tool: edit
        args:
          path: calc.py
          old_string: "return n + 2"
          new_string: "return n + 1"
  - content: 改好了，测试通过。
```

`verify` 就是这个任务的判据：全部命令 exit 0 才算通过。
**没有 `verify` 的任务永远不算通过**，所以一个 suite 不可能靠「什么都不做」通过。

`prompts:` 给 agent 多轮：同一个会话里一个接一个。**只有一个 prompt 的任务永远不会压缩**——
切点必须落在轮边界上，没发生过的轮切不了。想看到压缩、想量摘要多大，任务就得有第二个 prompt。

`expect: fail` 是给那些**必须不通过**的任务用的：它是 suite 的保险丝——
一个从来不失败的判据，会让每个任务都通过。
报告里每个任务带 `as_expected`（它有没有做到该做的），summary 里数了 `unexpected`（没做到的有几个）。

`require_tools` 写这个任务对工具的要求：这些要求里**有一条**要满足。
光看任务的结果是不够的：agent 用 shell 把文件重写一遍，照样能让检查通过，
而工具还是坏的。一条要求写清楚「哪些工具可以动手」和「它们必须动哪些文件」：

```yaml
require_tools:
  - tools: [edit, multi_edit]
    paths: [calc.py]
```

文件这一项是要紧的：改了另一个文件，不算做了这个任务。
写了这条要求的任务没法用 shell 绕过去，所以 `edit` 一坏，任务就会失败。

`config` 里可以写 `task.yaml` 旁边的 YAML 文件，这样一个任务能自带配置。
`evals/basic` 的任务用它带自己的权限规则：任务的模式和规则盖过命令行的模式，
并且把「绕开这个任务需要的工具」的路都堵上。

`script` 是脚本化模型：agent 的回答是写死的，不是问模型要来的。
它不需要 API key，所以带 `script` 的任务可以离线跑，而且 harness 自己的轨迹是可复现的；
不带 `script` 的任务走真实模型。
一个 suite 可以混着放脚本任务和真实模型任务，报告里每个任务都带 `mode`。

## 命令

```bash
coder eval <suite> \
  [-m MODEL] [-c SPEC ...] [--only ID ...] [--tag TAG ...] \
  [--format text|json] [--out FILE] [--keep] [--label NAME] \
  [--run-dir DIR] [--permission-mode bypass|default]
```

- `--only` 和 `--tag` 用来挑任务。
- `--format json` 把报告打成 json；`--out` 写的永远是 json 报告。
- `--run-dir` 把工作目录和会话留在指定的地方，`--keep` 保留这次运行的临时目录。
- `--permission-mode default` 会去问一个并不存在的人：agent 不会被卡住，
  但报告里会多一个 `approvals`——「本该由人介入多少次」。

## 报告

```json
{
  "format": "coder-eval-1.0",
  "label": "live-1",
  "suite": "evals/basic",
  "model": "nengpa/minimax-m2.7",
  "fingerprint": "sha256:9f2c…",
  "config": {"…": "fingerprint 的输入原样"},
  "started_at": 1762830000.0,
  "duration_seconds": 41.2,
  "summary": {
    "tasks": 3, "passed": 2, "failed": 1, "errors": 0, "unexpected": 0,
    "pass_rate": 0.667,
    "total_cost": 0.0412, "total_tokens_in": 12345, "total_tokens_out": 6789,
    "total_model_calls": 12, "total_tool_calls": 30,
    "compactions": 1, "summary_ratio_mean": 0.12, "summary_ratio_max": 0.12
  },
  "tasks": [
    {
      "id": "off-by-one", "mode": "live", "passed": true,
      "expect": "pass", "as_expected": true,
      "stop_reason": "end_turn", "error": "", "error_kind": "",
      "cost": 0.012, "tokens_in": 800, "tokens_out": 200,
      "model_calls": 7, "tool_calls": 9, "tool_errors": 1, "approvals": 0,
      "compactions": 1, "summary_ratios": [0.12],
      "duration_seconds": 5.1, "session_id": "20261111-a1b2c3",
      "setup": [],
      "verify": [
        {"command": "python -m pytest -q tests/test_calc.py",
         "exit_code": 0, "timed_out": false, "output": "1 passed"}
      ]
    }
  ]
}
```

litellm 的价格表里没有的模型，成本恒为 0，所以 token 一定要和成本一起报：
token 来自 provider，是可靠的。

`model_calls` 只数主循环的调用；子 agent 的调用不在里面，它们的**成本**在。

`tool_errors` 数失败的工具调用，被权限拒绝的也算。

`summary_ratios` 每次压缩给一个数：摘要多大，对着它替换掉的那段历史多大。
这个比值突然变大，要么是摘要变啰嗦了，要么是原文变啰嗦了。均值和最差值在整轮运行的
summary 里。

## fingerprint

fingerprint 是这次运行所用配置的哈希：模型、system prompt、工具、权限模式、上下文、沙箱。
**两次运行 fingerprint 相同才可比**；不同，说明 harness 变了，数字自然不一样。

fingerprint 的输入也原样放在报告里，所以两份报告一 diff，就能看出**是哪一项**变了：

```bash
diff <(jq -S .tasks before.json) <(jq -S .tasks after.json)
```

## 隔离

每个任务都跑在自己的地盘上：自己的工作目录、自己的会话、自己的模型。
会话、checkpoint、规则、用户记忆都被重定向到临时目录，
所以跑一次 eval 不会碰用户的数据，也不会碰仓库。

文件类工具出不了工作目录，`bypass` 模式也不行。
但 `bash` 可以：**本地跑 eval，模型写的命令就在你的机器上执行。**
请在容器里跑，或者在配置里换一个 `sandbox.type`。

## 对比

两份同一个 suite 的报告能回答「这次改 harness 到底有没有把 agent 改差」：

```bash
coder eval-compare after.json --against before.json
```

**退出码就是结论**：零 = 这次改动是好的；一 = 有任务原来能过、现在过不了了。
只比较两份报告**都有**的任务；`expect: fail` 的任务不算通过率，它只是保险丝。

```bash
coder eval-compare after.json \
  [--against before.json] [--max-regressions N] [--max-drop R] [--format text|json]
```

- 不给 `--against` 时，只检查这份报告本身：任务没做到该做的、或者 harness 没能评判它，都是问题。
- `--max-regressions` 和 `--max-drop` 是「原谅一点」的额度。
  真实模型不是确定性的，所以 live suite 需要留点余量；脚本 suite 不需要。
- 给了 `--against` 时，额度只管回归和通过率的下降：被额度原谅的回归不会**再报一遍**。
  但保险丝被打破（`expect: fail` 的任务通过了）和 harness 评判不了的任务，任何额度都不原谅。

## 拉取请求的检查

`.github/workflows/eval.yaml` 会跑一遍这个 PR 的 suite，再用**基线的 harness** 跑一遍，然后对比：

```bash
git worktree add /tmp/base <基线那个 commit>
cp -r evals/offline /tmp/base/evals/
PYTHONPATH=/tmp/base/src python -c "from coderagent.ui.cli import app; app()" \
  eval /tmp/base/evals/offline --label base --format json --out base.json
coder eval-compare head.json --against base.json
```

CI 跑的是 `evals/offline`：每个任务都是脚本化的，所以这个检查**不需要 API key**，
而且每次说的都是同一件事。它里面还有一个**必须不通过**的任务，
所以「判据从来不失败」这种坏情况藏不住。

`live` 这个 job 拿 `evals/basic` 和真实模型做同样的事。它只能手动触发，
需要模型的密钥，而且**什么都不原谅**：模型不是确定性的，
所以这个 job 失败是「再跑一遍」的理由，不是结论。

两个 job 的灵敏度不一样。脚本那个是精确的：harness 弄坏一个工具，
对应的任务就会失败，job 会说出来。live 那个不是：模型碰到坏掉的工具
常常会绕道走，所以一个坏掉的 harness 可能只让八个任务里的一个失败。
**脚本那个是闸门，live 那个是信号。**

## 样例任务集

`evals/basic` 里有八个任务。它们都没有 `script`，所以跑的是真实模型，需要 API key：

```bash
coder eval evals/basic --label live-1 --format json --out /tmp/eval.json
```

| 任务 | 内容 |
|---|---|
| `off-by-one` | `calc.py` 里的 bug，agent 得自己找出来并修好 |
| `import-error` | 模块 import 了一个不存在的名字 |
| `rename-symbol` | 一个函数，模块里和调用它的地方都得改名 |
| `create-file` | 一个还不存在的文件，agent 得把它写出来 |
| `cli-flag` | 脚本无视了传进来的参数 |
| `config-value` | 配置文件里的一个值要改 |
| `grep-count` | 问仓库里的文件，然后把这个答案写进文件 |
| `no-op` | 一个已经做好的任务：agent 得**什么都别改** |

最后一个是刻意的：不该改的时候乱改，和该改的时候不改，是同一种 bug。

八个任务里有五个把要改的文件「保护」起来：任务自己的规则挡住其它所有写法，
而且任务要求 `edit` 工具**在这个文件上**成功用过。
所以 `edit` 一坏，任务就失败，而不是被绕过去。

除了 `no-op`，每个任务在 agent 开始之前都是**没通过**的——一个什么都不做就能过的任务是个坏任务。
`tests/coderagent/eval/test_suite.py` 盯着这件事。

`evals/offline` 是另一个 suite：六个任务，全是脚本化的，全离线。
`broken-check` 是这个 suite 的保险丝：它的判据**必须**失败，
所以一个从来不失败的判据藏不住。`multi-turn` 有三个 prompt：每个 prompt 一轮，同一个会话。

想不花 API key 就跑一个任务，给它加一段 `script`：agent 的回答是写死的，轨迹每次都一样。
