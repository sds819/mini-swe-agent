# The sandbox

The commands of the agent run in a sandbox. By default the sandbox is the
machine of the user.

```yaml
sandbox:
  type: local
```

## The remote sandboxes

The sandboxes of mini-swe-agent are used as they are:

| `sandbox.type` | What it does |
|---|---|
| `local` | The commands run on this machine |
| `swerex_docker` | A Docker container that SWE-ReX manages |
| `swerex_modal` | A container on Modal |
| `bubblewrap` | A sandbox without root |
| `contree` | A container without root |

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
```

The options that the environment does not know are ignored, so the same
configuration works for every kind of sandbox. A full path of a class works as
well, which is the way to use an environment of your own:

```yaml
sandbox:
  type: my_package.my_module.MyEnvironment
```

The credentials of the remote sandboxes (`SWE_REX_SERVER_URL`,
`SWE_REX_API_KEY`, …) come from the environment or from the `.env` file.

## What the interface shows

The bar at the top of the interface names the sandbox when it is not the local
one, and `/sandbox` shows the whole configuration:

```
type: swerex_docker
network: restricted
writable roots: .
environment: swerex_docker
```

## What is still local

The tools that read and write files (`read`, `write`, `edit`, …) work on the
files of the machine of the user, because the environment of mini-swe-agent
only runs commands. Only the commands of the `bash` tool go into the sandbox.

The magic of mini-swe-agent, where a command that prints
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` ends the task, is switched off in the
remote sandboxes as well: a turn of the coding agent ends when the model says
so.
