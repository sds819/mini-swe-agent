# Skills

A skill is a package of instructions, scripts and resources for a kind of task
that comes back often.

```
.coderagent/skills/pdf-report/
├── SKILL.md
├── scripts/
│   └── make_report.py
└── assets/
    └── template.docx
```

The `SKILL.md` says what the skill is for. The model sees the name and the
description of every skill, and loads the whole one when the description fits
the task:

```markdown
---
name: pdf-report
description: Make a PDF report out of a folder of notes.
---
Run `scripts/make_report.py` to build the report:

    python scripts/make_report.py notes/ --template assets/template.docx

The report lands in `report.pdf`.
```

| Field | What it is | Default |
|---|---|---|
| `name` | The name of the skill | The name of the directory |
| `description` | What it is for, and when to use it | |

The body is the instruction that the model reads when it loads the skill. A
file without a front matter is ignored.

## Where a skill is looked for

| Where | What |
|---|---|
| `.coderagent/skills/*/SKILL.md` | The skills of the project |
| `~/.coderagent/skills/*/SKILL.md` | The skills of the user |

The project comes last, so a project may replace a skill of the user with the
same name. `MSWEA_CODER_HOME` moves the directory of the user.

`/skills` lists them:

```
pdf-report       Make a PDF report out of a folder of notes.
                 /path/to/project/.coderagent/skills/pdf-report
```

## How the model uses a skill

The index of the skills goes into the system prompt, so the model knows what
is on the table without paying for it:

```
<skills>
These skills are available. Load one with the `skill` tool when its description fits the task.
- pdf-report: Make a PDF report out of a folder of notes.
</skills>
```

When the task fits, the model calls the `skill` tool with the name. The tool
gives back the body of the `SKILL.md` and the path of the directory, so the
model knows where the scripts are. The scripts themselves are run with
`bash`, in the working directory of the session.

A skill is a package of steps, not a program: the model reads the
instructions and follows them, and the scripts are only there to make the
steps easier.

## A skill and a command

| | A skill | A command |
|---|---|---|
| Who calls it | The model, when the description fits | The user, with `/name` |
| What it is | Instructions the model follows | A message the user sends |
| What it leaves | Files, reports, commits | A message in the conversation |

A command is in `.coderagent/commands/*.md`, see
[The commands](coderagent_commands.md). A skill is in
`.coderagent/skills/<name>/SKILL.md`.

## The permissions

The `skill` tool is a tool that is asked for, like `bash`. Without a terminal
nobody can answer, so in a script the call is refused:

```bash
coder --task "..." --permission-mode bypass
```

or a rule of your own:

```yaml
# .coderagent/rules.yaml
rules:
  - tool: skill
    pattern: "*"
    decision: allow
```
