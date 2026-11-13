# The memory

The agent remembers two kinds of things: what it learned about the project and
what the user likes. The first is written by the agent, the second only after
the user says so.

## What the agent reads

Everything below goes into the context of the model, before the
conversation, in this order:

| Where | What it is |
|---|---|
| `~/.coderagent/CLAUDE.md` | The instructions and the preferences of the user |
| `AGENTS.md` | The instructions of the project |
| `CLAUDE.md` | The instructions of the project |
| `.coderagent/memory/*.md` | What the agent learned about the project |
| `~/.coderagent/CLAUDE.md` | The preferences of the user |

An `AGENTS.md` in a subdirectory is read when the agent touches something in
it, and not before.

The file of the user is read twice: once as the instructions of the user, and
once as the memory of the user. The preferences that `/memory confirm` writes
are therefore read at the start of the next session.

The project memory is every markdown file of `.coderagent/memory/`, so you
may write `conventions.md` or `architecture.md` next to the file the agent
keeps for itself.

## What the agent writes

When a session ends, the model is asked what is worth remembering for the
sessions that come after it. A session ends when the interface is closed, when
`/clear` starts a new one, and at the end of a run of `coder --task ...`. It
answers with two lists:

```json
{
  "project_facts": ["The tests of the parser run with `pytest -m slow`"],
  "user_preferences": ["The comments of the user are in Chinese"]
}
```

The **project facts** are objective things about the project that are not in
the code and not in the instructions. They are written right away, into
`.coderagent/memory/projects.md`:

```markdown
# Project memory

- The tests of the parser run with `pytest -m slow`
```

The **user preferences** are how the user likes to work. They go into the
instructions of every session, so a wrong one is expensive. They wait for a
confirmation:

```markdown
# Preferences waiting for a confirmation

- The comments of the user are in Chinese
```

That file is `.coderagent/pending-memory.md`.

## The commands

```bash
/memory                # the memory of the project, the pending preferences, the memory of the user
/memory confirm        # write the pending preferences to ~/.coderagent/CLAUDE.md
/memory forget <text>  # remove a line from the project memory or from the pending file
```

`/memory confirm` moves the pending preferences into `~/.coderagent/CLAUDE.md`,
under a heading of their own:

```markdown
## Preferences

- The comments of the user are in Chinese
```

`/memory forget` takes the text of the line to remove. It works on the
project memory and on the pending file, not on the file of the user.

## The rules

- A fact that is already there is not written twice. The comparison ignores
  the case and the punctuation.
- The project memory does not grow past 200 lines. The pending file has the same
  limit. When it would, nothing is written and the agent says so in the log:
  the file has to be tidied up first.
- The preferences of the user are never written without the confirmation.
- The project facts are written without a confirmation: they are about the
  project, and the user can change them like any other file.

## The cost

The reflection is a model call like any other. It is not part of a turn, so
it is not in the `cost` of a turn, but it is in the bill of the session: it
lands in the event log, and `session_cost`, `/cost` and `coder export` count
it.

A turn that failed or that ran out of the money budget is not settled: there is
nothing to remember, and no money to do it. A turn that stopped at the token
limit is settled like any other.

## Turning it off

```yaml
memory:
  enabled: false
```

The model is not even asked, and the memory of the project and of the user is
not put into the context of the model any more. The path of the project file
is yours to change, the path of the user file only in its file name — it is
always written into the directory of the user:

```yaml
memory:
  project_path: ".coderagent/memory"
  user_path: "~/.coderagent/CLAUDE.md"
```

The file with the preferences that wait for a confirmation is always
`<cwd>/.coderagent/pending-memory.md`.
