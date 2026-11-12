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
| `docker` | A Docker container |
| `singularity` | A Singularity container |
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

The container works in its own directory, not in the directory of the session:
the path of the host does not exist in a container. Give the container a
directory of its own with the `cwd` option:

```yaml
sandbox:
  type: swerex_docker
  image: python:3.11
  cwd: /workspace
```

## What the interface shows

The bar at the top of the interface names the sandbox when it is not the local
one, and `/sandbox` shows the whole configuration:

```
type: swerex_docker
image: python:3.11
environment: swerex_docker
```

The options that are in effect are listed between the type and the environment.

## The sandbox has no policy of its own

The sandbox is the environment of mini-swe-agent, so it has no network policy
and no list of writable directories. A network policy is a property of the
environment, and it is written there — with the options that the environment
knows. The `docker` sandbox takes the arguments of the `docker` command:

```yaml
sandbox:
  type: docker
  image: python:3.11
  run_args: ["--rm", "--network", "none"]
```

Every sandbox has its own options: the `swerex_docker` one, for instance, takes
`deployment_extra_kwargs` for the deployment of SWE-ReX. The options that the
environment does not know are ignored, so a `run_args` under `swerex_docker`
is dropped without a word.

The paths the agent may touch are a property of the agent, not of the sandbox.
They are bounded by the permission layer: `permissions.deny_paths` for the paths
that are off limits and `permissions.include_dirs` for the ones outside the
directory of the session that are allowed.

A configuration that still has `sandbox.network` or `sandbox.writable_roots`
keeps working: they are unknown options now, and unknown options are ignored.

## What is still local

The tools that read and write files (`read`, `write`, `edit`, …) work on the
files of the machine of the user, because the environment of mini-swe-agent
only runs commands. Only the commands of the `bash` tool go into the sandbox.

The magic of mini-swe-agent, where a command that prints
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` ends the task, is switched off in the
remote sandboxes as well: a turn of the coding agent ends when the model says
so.
