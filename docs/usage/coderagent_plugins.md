# Plugins

A plugin adds tools, commands, hooks or model backends to the agent. A plugin is
a directory with a `plugin.py` in it:

```
.coderagent/plugins/hello/
└── plugin.py
```

The plugin runs in the process of the agent, without a sandbox. It is only
loaded when the user has trusted it.

The code of a plugin is not run before that decision. Finding the plugins only
reads their source, to see whether they have a `register`; the module is
imported when a trusted plugin is loaded. So `/plugins` never runs the code of
a plugin, and an untrusted plugin cannot do anything but sit on the disk.

## Where a plugin is looked for

| Where | What |
|---|---|
| `~/.coderagent/plugins/*/` | The plugins of the user |
| `.coderagent/plugins/*/` | The plugins of the project |
| The entry point group `coderagent.plugins` | The plugins that are installed with pip |

The name of a plugin is the name of its directory. A plugin of the project and
a plugin of the user with the same name are **both** loaded: the name is only
the name of the plugin, the trust is remembered by that name.

## Trusting a plugin

```bash
/plugins            # the plugins that were found, and what the user answered for them
/plugins trust hello
```

A plugin that was not trusted is never loaded, and nothing is asked: the
answer comes from `/plugins trust`. The answer is remembered in
`~/.coderagent/trusted-plugins.json` (`MSWEA_CODER_HOME` moves it), so it is
given once and holds for every session.

```
hello            trusted      directory
other            not trusted  directory
```

The last column says where the plugin came from: a directory, or an entry
point of an installed package.

A plugin that the user refused stays away until the name is trusted again. The
trust is by name, so it holds for the plugin of the project and for the plugin
of the user that have the same name.

## The API of a plugin

The plugin file has a `register` function. The function gets the extension
registry:

```python
# .coderagent/plugins/hello/plugin.py
from coderagent.tools.base import ToolResult
from coderagent.ui.commands import Command


class HelloTool:
    name = "hello"
    description = "Say hello to the user."

    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

    def run(self, params, ctx):
        return ToolResult(f"Hello, {params.get('name', 'there')}!")


def hello(context, argument):
    context.say("Hello!")


def register(registry):
    registry.tools.register(HelloTool())
    registry.commands.append(Command(name="hello", description="Say hello", handler=hello))
```

The registry has four parts:

| Part | What it is |
|---|---|
| `registry.tools` | The tools the model may call |
| `registry.commands` | The slash commands the user may type |
| `registry.hooks` | The hooks, in the format of the configuration |
| `registry.model_backends` | The model backends, by name |

The tools, the commands and the hooks are used by the agent. The model
backends are not wired yet: a plugin may fill the table, but the agent does
not read it.

A tool that the plugin registers goes through the same permission check as the
tools of the agent, so the rules of the project apply to it as well.

A command that the plugin registers works like a built-in one: the user types
`/hello`, and the handler gets the context of the session and the text of the
line.

## Writing a plugin that is installed with pip

```python
# pyproject.toml
[project.entry-points."coderagent.plugins"]
hello = "hello_plugin:plugin"
```

The object the entry point points at is loaded a little more loosely: it is
either a `register` function or an object with a `register` method. A
`plugin.py` has to use the function — a class with a `register` method is
found by the search, but it is not loaded afterwards and the plugin stays
empty. The one exception is a class whose name is exactly `plugin`: it is
loaded like the function would be.
