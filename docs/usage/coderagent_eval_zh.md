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
prompt: |
  calc.py 里的 add_one 差一。修好它，让测试通过。
setup:                        # 可选，在 agent 开始前于工作目录执行
  - pip install -e .
verify:                       # 必填，在 agent 结束后执行；全部 exit 0 才算通过
  - python -m pytest -q tests/test_calc.py
timeout: 300                  # 可选，agent 这一轮的墙钟秒数（默认 300）
verify_timeout: 300           # 可选，每条 verify 命令的秒数（默认 300）
tags: [bugfix]                # 可选
config:                       # 可选，配置覆盖：YAML 文件路径或 `a.b=c`
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
    "tasks": 3, "passed": 2, "failed": 1, "errors": 0, "pass_rate": 0.667,
    "total_cost": 0.0412, "total_tokens_in": 12345, "total_tokens_out": 6789,
    "total_model_calls": 12, "total_tool_calls": 30
  },
  "tasks": [
    {
      "id": "off-by-one", "mode": "live", "passed": true,
      "stop_reason": "end_turn", "error": "", "error_kind": "",
      "cost": 0.012, "tokens_in": 800, "tokens_out": 200,
      "model_calls": 7, "tool_calls": 9, "tool_errors": 1, "approvals": 0,
      "compactions": 0, "duration_seconds": 5.1, "session_id": "20261111-a1b2c3",
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

## 样例任务集

`evals/basic` 里有三个任务。它们都没有 `script`，所以跑的是真实模型，需要 API key：

```bash
coder eval evals/basic --label live-1 --format json --out /tmp/eval.json
```

| 任务 | 内容 |
|---|---|
| `off-by-one` | `calc.py` 里的 bug，agent 得自己找出来并修好 |
| `create-file` | 一个还不存在的文件，agent 得把它写出来 |
| `no-op` | 一个已经做好的任务：agent 得**什么都别改** |

第三个是刻意的：不该改的时候乱改，和该改的时候不改，是同一种 bug。

想不花 API key 就跑一个任务，给它加一段 `script`：agent 的回答是写死的，轨迹每次都一样。
