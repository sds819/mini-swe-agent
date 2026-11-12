# The eval harness

The coding agent is a harness: an event log, a permission layer, structured tools,
a context engine, a trace. A harness that is never measured is a harness that is
never improved. `coder eval` runs a suite of tasks and reports what the agent
did, so that a change of the harness can be compared with the change before it.

```bash
coder eval evals/basic --format json --out /tmp/eval.json
```

## The suite

A suite is a directory, every task is a directory inside it. A task has a
`task.yaml` and, next to it, the files that are the initial state of the working
directory of the agent.

```yaml
# evals/basic/off-by-one/task.yaml
id: off-by-one                # optional, the name of the directory by default
prompt: |
  The function `add_one` in calc.py is off by one. Fix it so that the test passes.
setup:                        # optional, in the working directory, before the agent
  - pip install -e .
verify:                       # required, in the working directory, after the agent
  - python -m pytest -q tests/test_calc.py
timeout: 300                  # optional, the seconds of the agent (default 300)
verify_timeout: 300           # optional, the seconds of each verify command
expect: pass                  # optional, `pass` (default) or `fail`
tags: [bugfix]                # optional
require_tools:               # optional, the tools the task needs, and the files they touch
  - tools: [edit, multi_edit]
    paths: [calc.py]
config:                       # optional, a yaml file or `a.b=c` overrides
  - permissions.yaml          # a yaml file next to the task.yaml
  - agent.max_turns=20
script:                       # optional, the scripted model. Empty means: the real model.
  - content: Let me look at the file first.
    tool_calls:
      - tool: read
        args: {path: calc.py}
  - content: Found it. Fixing it.
    tool_calls:
      - tool: edit
        args:
          path: calc.py
          old_string: "return n + 2"
          new_string: "return n + 1"
  - content: The test passes now.
```

Every file of the task directory that is not a yaml file is a fixture: it is
copied into the working directory before the agent starts.

The `verify` commands are the judgement of the task: the task passed when all of
them exit with 0. A task without a `verify` never passes, so a suite cannot
pass by doing nothing.

`expect: fail` is for the tasks that must *not* pass: a guard that keeps the
suite honest, because a check that never fails would let every task pass. The
report says whether a task did what it was supposed to do (`as_expected`), and
the summary counts the ones that did not (`unexpected`).

`require_tools` names what the task needs from the tools: one of the requirements
has to be met. The result of the task alone is not enough, because an agent
that rewrites the file with the shell would pass the check while the tool
stayed broken. A requirement names the tools that may do the work and the
files they have to touch:

```yaml
require_tools:
  - tools: [edit, multi_edit]
    paths: [calc.py]
```

The file matters: an edit of another file is not the work of the task. A task
that says this cannot be solved with the shell, so a broken `edit` shows up as
a failed task.

A `config` entry may be a yaml file next to the `task.yaml`, so that a task
brings its own settings. The tasks of `evals/basic` use it for their permission
rules: the mode and the rules of the task win over the mode of the command, and
they forbid the routes around the tool the task needs.

The `script` is a scripted model: the answers of the agent are written down
instead of asked for. It needs no API key, so a task with a script runs offline,
and it makes the trajectory of the harness itself reproducible. A task without a
script runs against the real model. A suite may mix scripted and live tasks, and
the report says which is which (`"mode"`).

## The command

```bash
coder eval <suite> \
  [-m MODEL] [-c SPEC ...] [--only ID ...] [--tag TAG ...] \
  [--format text|json] [--out FILE] [--keep] [--label NAME] \
  [--run-dir DIR] [--permission-mode bypass|default]
```

- `--only` and `--tag` select the tasks of the suite.
- `--format json` prints the report as json. `--out` always writes the json report.
- `--run-dir` keeps the working directories and the sessions in a place you choose.
- `--keep` keeps the temporary directory of the run.
- `--permission-mode default` asks for the approval of a human that is never
  there: the agent is not blocked, but the report counts the questions it would
  have asked (`approvals`).

## The report

```json
{
  "format": "coder-eval-1.0",
  "label": "live-1",
  "suite": "evals/basic",
  "model": "nengpa/minimax-m2.7",
  "fingerprint": "sha256:9f2c…",
  "config": {"…": "the input of the fingerprint, as it was"},
  "started_at": 1762830000.0,
  "duration_seconds": 41.2,
  "summary": {
    "tasks": 3, "passed": 2, "failed": 1, "errors": 0, "unexpected": 0,
    "pass_rate": 0.667,
    "total_cost": 0.0412, "total_tokens_in": 12345, "total_tokens_out": 6789,
    "total_model_calls": 12, "total_tool_calls": 30
  },
  "tasks": [
    {
      "id": "off-by-one", "mode": "live", "passed": true,
      "expect": "pass", "as_expected": true,
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

The cost of a model that litellm does not know is 0, so the tokens are always in
the report next to it: they come from the provider and they are reliable.

`model_calls` counts the calls of the main loop. The calls of the sub agents are
not in it, their cost is.

`tool_errors` counts the tool calls that failed, the ones that were denied
included.

## The fingerprint

The fingerprint is the hash of the configuration the agent ran with: the model,
the system prompt, the tools, the permission mode, the context and the sandbox.
Two runs with the same fingerprint are comparable, two runs with a different one
are not: the harness changed, so the numbers moved for that reason.

The input of the fingerprint is in the report as well, so a diff of two reports
says *what* changed:

```bash
diff <(jq -S .tasks before.json) <(jq -S .tasks after.json)
```

## The isolation

Every task runs on its own: its own working directory, its own session, its own
model. The sessions, the checkpoints, the rules and the memory of the user go to
a temporary directory, so a run of the eval does not touch the data of the user
nor the repository.

The file tools cannot leave the working directory, not even in the `bypass`
mode. The `bash` tool can: **a local eval runs the commands the model writes on
your machine.** Run it in a container, or with a sandbox type of your choice
(`sandbox.type` in the configuration).

## The comparison

Two reports of the same suite say whether a change of the harness made the agent
worse:

```bash
coder eval-compare after.json --against before.json
```

The exit code is the verdict: zero when the change is good, one when a task
that used to pass does not pass any more. Only the tasks that both runs have
are compared, and a task with `expect: fail` is not a rate but a guard.

```bash
coder eval-compare after.json \
  [--against before.json] [--max-regressions N] [--max-drop R] [--format text|json]
```

- Without `--against` the report is only checked against what its tasks were
  supposed to do: a task that did not, or a task the harness could not grade,
  is a problem.
- `--max-regressions` and `--max-drop` forgive a little. The real model is not
  deterministic, so a live suite needs a margin; a scripted suite does not.
- With `--against` the margin applies to the regressions and to the fall of the
  rate. A task that regressed is forgiven by the margin, not reported twice.
  The guard of a suite and a task the harness could not grade are never
  forgiven.

## The check of the pull request

`.github/workflows/eval.yaml` runs the suite of the pull request, runs it
again with the harness of the base, and compares the two:

```bash
git worktree add /tmp/base <the commit of the base>
cp -r evals/offline /tmp/base/evals/
PYTHONPATH=/tmp/base/src python -c "from coderagent.ui.cli import app; app()" \
  eval /tmp/base/evals/offline --label base --format json --out base.json
coder eval-compare head.json --against base.json
```

The suite of the CI is `evals/offline`: every task of it is scripted, so the
check needs no API key and says the same thing every time. It holds a task that
must fail, so the check of the suite cannot be vacuous.

The job `live` does the same with `evals/basic` and the real model. It is
manual, it needs the secrets of the model, and it forgives nothing: the real
model is not deterministic, so a failure of the job is a reason to run it
again, not a verdict.

The two jobs are not equally sensitive. The scripted one is exact: a harness
that breaks a tool fails its task, and the job says so. The live one is not:
a model that meets a broken tool often finds another way, so a broken harness
can cost a single task out of eight. The scripted job is the gate; the live
one is the signal.

## The example suite

`evals/basic` holds eight tasks. They have no `script`, so they run against the
real model and they need an API key:

```bash
coder eval evals/basic --label live-1 --format json --out /tmp/eval.json
```

| task | what it is |
|---|---|
| `off-by-one` | a bug in `calc.py`, the agent has to find it and fix it |
| `import-error` | a module that imports a name that does not exist |
| `rename-symbol` | a function that has to be renamed in the module and in its callers |
| `create-file` | a file that does not exist yet, the agent has to write it |
| `cli-flag` | a script that ignores the argument it is given |
| `config-value` | a value in a configuration file that has to change |
| `grep-count` | a question about the files of the repository, answered in a file |
| `no-op` | a task that is already done: the agent has to leave the code alone |

The last one is deliberate: an agent that changes what it should not is as much
a bug as an agent that changes nothing.

Five of the tasks protect the file they change: the rules of the task refuse
every other way of writing it, and the task needs the `edit` tool to have
worked on that very file. So a broken `edit` fails the task instead of being
routed around.

Every task but `no-op` fails its check before the agent starts, so a task that
is solved by doing nothing is a broken task. `tests/coderagent/eval/test_suite.py`
keeps an eye on that.

`evals/offline` is the other suite: five tasks, all scripted, all offline. The
`broken-check` task is the guard of the suite: its check has to fail, so a check
that never fails cannot hide.

To run a task without an API key, give it a `script`: the answers of the agent
are written down, and the trajectory is the same every time.
