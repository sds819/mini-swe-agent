# The model routing

The agent does not always need the same model. The summary of a compacted
context, the reflection at the end of a session and a sub agent that looks for
a symbol do not need the strongest model you have, and the model that answers
the main loop should get stronger when the job gets big.

## The purposes

A purpose is a job, not a model. The routing says which model does which job:

```yaml
model:
  model_name: anthropic/claude-sonnet-4-5
  routing:
    main: anthropic/claude-sonnet-4-5
    cheap: deepseek/deepseek-flash
    summarize: deepseek/deepseek-flash
    reflect: deepseek/deepseek-flash
    strong: anthropic/claude-opus-4-1
```

| Purpose | What it is for |
|---|---|
| `main` | The agent itself |
| `cheap` | The small jobs: the sub agents that look around |
| `summarize` | The summary of a compacted context |
| `reflect` | What the session writes into the memory |
| `strong` | A stronger model, when the job is big |

A purpose that is not routed uses the model of the main loop.

The summary has a setting of its own, which wins over the routing:

```yaml
context:
  summarize_model: deepseek/deepseek-flash
```

## The rules of the main loop

Without any rule the routing follows a policy of its own:

| The state of the session | What happens |
|---|---|
| The budget is 80% used | A cheaper model takes over |
| The token budget is 80% used | A cheaper model takes over |
| The context is over 50k tokens | A stronger model takes over |
| The session is over 30 turns | A stronger model takes over |

The budget is `agent.cost_limit` and the token budget is `agent.token_limit`. A
model without a price spends no money, so the token budget is the budget that
counts for it.

A stronger model only takes over when `routing.strong` is set. A cheaper one
only takes over when `routing.cheap` is set.

## Your own rules

A rule is a condition on the state of the session, and the purpose it leads
to:

```yaml
model:
  routing:
    strong: anthropic/claude-opus-4-1
  routing_rules:
    - when: "tokens > 50000"
      purpose: strong
    - when: "calls > 20"
      purpose: cheap
```

The condition is a number, an operator and a number:

```
<key> <operator> <number>
```

The operators are `>`, `>=`, `<`, `<=`, `==` and `!=`. The keys are the state
of the session:

| Key | What it is |
|---|---|
| `tokens` | The size of the context |
| `turns` | The turns of the session |
| `calls` | The model calls of the session |
| `cost` | What the session has cost so far |
| `budget` | The cost limit of the session |

The rules are **parsed, not evaluated**. A condition that is not of that form
never holds, and it never runs code: a configuration file cannot make the
agent do anything.

The rules are tried before the purpose of the call, and before the policy of
the main loop. The first rule that holds wins.

## What the user sees

The status bar shows the model of the moment. When the model changes, a
message comes into the conversation of the interface:

```
Switched from deepseek/deepseek-flash to anthropic/claude-opus-4-1: the context has grown
```

The reason is one of these: the budget is nearly used up, the token budget is
nearly used up, the context has grown, the session has many turns, or the rule
that held. In the trace the change is a `state_change` event, with the model,
the previous one and the reason.

## Changing the model by hand

```bash
/model                # the model of the session and the routing
/model deepseek/deepseek-chat
```

A model that the user picked wins over every rule. It changes the model of
the main loop; the other purposes keep their routing.

## The money

The routing looks at the budget of the **session**, not at the total of the
process. A new session starts at zero, so it is not punished for what the
session before it spent.

The cost of a model that runs on another model is booked on the main one, so
the budget of the session holds every call, whatever purpose it was made
for.
