# The trace of a session

Every session is written to an event log, and that log is the source of truth.
The `export` command turns it into a trace, with the metrics of the session.

```bash
coder export --session 20261106-a1b2c3 --format json --out trace.json
coder export --session 20261106-a1b2c3 --format otel --out trace.otlp
coder export --cwd .                       # the newest session of this directory
```

Without `--out` the trace goes to the standard output.

## The json format

The format is `coder-agent-1.0`, next to the `mini-swe-agent-1.1` of
mini-swe-agent:

```json
{
  "trajectory_format": "coder-agent-1.0",
  "session": {
    "id": "20261106-a1b2c3",
    "cwd": "/home/me/project",
    "created_at": 1762310400.0,
    "updated_at": 1762310900.0,
    "state": "done",
    "model_name": "deepseek/deepseek-flash",
    "permission_mode": "default",
    "turn_count": 3,
    "total_cost": 0.42
  },
  "events": [
    {
      "session_id": "20261106-a1b2c3",
      "type": "user_message",
      "timestamp": 1762310400.0,
      "payload": {"content": "fix the test"}
    }
  ],
  "metrics": {
    "total_cost": 0.42,
    "total_tokens_in": 120433,
    "total_tokens_out": 8421,
    "model_calls": 9,
    "tool_calls": 60,
    "per_tool": {"read": 42, "bash": 13, "edit": 5},
    "per_purpose_cost": {"main": 0.38, "cheap": 0.04},
    "per_model_cost": {"deepseek/deepseek-flash": 0.38},
    "duration_seconds": 412.3,
    "compactions": 3,
    "summary_ratios": [0.06, 0.07, 0.05],
    "errors": 0
  }
}
```

`summary_ratios` holds one number per compaction: how much of the compacted
history the summary kept. It is the gauge of the quality of the summary.

## The otel format

The same session as OTLP/JSON: one span per turn, one span per tool call. The
file goes into Jaeger, Tempo or any other place that reads OTLP.

```json
{
  "resourceSpans": [
    {
      "resource": {"attributes": [{"key": "session.id", "value": {"stringValue": "20261106-a1b2c3"}}]},
      "scopeSpans": [
        {
          "scope": {"name": "coderagent"},
          "spans": [
            {
              "name": "turn",
              "spans": [{"name": "tool.read", "parentSpanId": "..."}]
            }
          ]
        }
      ]
    }
  ]
}
```

## Where the money went

The `/cost` command shows the same metrics, with the cost of the session split
by purpose, by model and by tool:

```
model: deepseek/deepseek-flash
calls: 9
tokens in the context: 120433
tokens spent: 128854
cost so far: $0.4200
cost: $0.4200
tokens: 120433 in, 8421 out
model calls: 9
tool calls: 60
duration: 412.3s
by purpose:
  main        $0.3800
  cheap       $0.0400
by model:
  deepseek/deepseek-flash  $0.4200
by tool:
  bash         13
  edit          5
  read         42
```

The `purpose` is the job the model was called for: `main` for the agent itself,
the purpose of the sub agent for a delegated task, `summarize` for the summary
of a compacted context and `reflect` for the memory of the session.
