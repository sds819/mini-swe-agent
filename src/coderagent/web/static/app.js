"use strict";

const CLIENT = { "X-Coder-Client": "1" };

const state = {
  sessionId: null,
  seq: 0,
  stream: null,
  cards: {},
  assistant: null,
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const opts = Object.assign({}, options, {
    headers: Object.assign({ "X-Coder-Client": "1" }, options.headers || {}),
  });
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  if (!response.ok) throw new Error(`${response.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

// -- the conversation ------------------------------------------------------

function bubble(className, text) {
  const node = el("div", `bubble ${className}`, text || "");
  document.getElementById("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function toolCard(item) {
  const card = el("div", "tool");
  const header = el("header");
  header.appendChild(el("strong", "", item.tool || "tool"));
  if (item.summary) header.appendChild(el("span", "", item.summary));
  card.appendChild(header);
  const body = el("div", "body", "running…");
  card.appendChild(body);
  document.getElementById("messages").appendChild(card);
  card.scrollIntoView({ block: "end" });
  return card;
}

function fillTool(card, item) {
  if (!card) return;
  const body = card.querySelector(".body");
  body.className = `body ${item.is_error ? "bad" : "ok"}`;
  if (item.diff) {
    body.innerHTML = "";
    body.appendChild(diffView(item.diff));
  } else {
    body.textContent = item.content || "";
  }
}

function diffView(diff) {
  const pre = el("pre", "diff");
  for (const line of diff.split("\n")) {
    let cls = "";
    if (line.startsWith("+")) cls = "add";
    else if (line.startsWith("-")) cls = "del";
    else if (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) cls = "meta";
    pre.appendChild(el("div", cls, line));
  }
  return pre;
}

function renderApproval(item) {
  const card = el("div", "tool approval");
  const header = el("header");
  header.appendChild(el("strong", "", `approval: ${item.tool}`));
  if (item.reason) header.appendChild(el("span", "", item.reason));
  card.appendChild(header);
  const body = el("div", "body", JSON.stringify(item.params || {}, null, 2));
  card.appendChild(body);
  const buttons = el("div", "buttons");
  for (const [label, decision] of [["Allow", "allow"], ["Deny", "deny"], ["Always allow", "always"]]) {
    const button = el("button", decision === "allow" ? "primary" : "", label);
    button.onclick = async () => {
      buttons.innerHTML = "";
      buttons.appendChild(el("span", "", "answered…"));
      try {
        await api(`/api/approvals/${item.id}`, { method: "POST", body: { decision } });
      } catch (error) {
        buttons.appendChild(el("span", "", `error: ${error.message}`));
      }
    };
    buttons.appendChild(button);
  }
  card.appendChild(buttons);
  document.getElementById("messages").appendChild(card);
  card.scrollIntoView({ block: "end" });
  return card;
}

function renderTodos(todos) {
  let panel = document.getElementById("todo-panel");
  if (!panel) {
    panel = el("div", "todos");
    panel.id = "todo-panel";
    document.getElementById("messages").appendChild(panel);
  }
  panel.innerHTML = "";
  for (const todo of todos || []) {
    panel.appendChild(el("div", todo.status === "completed" ? "done" : "", todo.content || ""));
  }
}

function render(item) {
  switch (item.kind) {
    case "user_message":
      bubble("user", item.content);
      state.assistant = null;
      break;
    case "assistant_message": {
      const content = item.content || "";
      if (state.assistant) {
        /* the answer was streamed into this bubble; the message is the whole of it */
        state.assistant.textContent = content;
        state.assistant = null;
        break;
      }
      bubble("assistant", content);
      state.assistant = null;
      break;
    }
    case "text_delta": {
      if (!state.assistant) {
        state.assistant = bubble("assistant", "");
      }
      state.assistant.textContent += item.content;
      state.assistant.scrollIntoView({ block: "end" });
      break;
    }
    case "reasoning_delta":
    case "reasoning":
      break;
    case "tool_call":
      state.cards[item.tool_call_id] = toolCard(item);
      break;
    case "tool_result":
      fillTool(state.cards[item.tool_call_id], item);
      break;
    case "approval_request":
      state.cards[`approval-${item.id}`] = renderApproval(item);
      break;
    case "approval_response": {
      const card = state.cards[`approval-${item.id}`];
      if (card) {
        card.querySelector(".buttons").innerHTML = "";
        card.querySelector(".buttons").appendChild(
          el("span", "", item.timed_out ? "no answer: denied" : `answered: ${item.decision}`)
        );
      }
      break;
    }
    case "todos":
      renderTodos(item.todos);
      break;
    case "command_output":
      bubble("command", item.text);
      break;
    case "error":
      bubble("error", item.error);
      break;
    case "compaction":
      bubble("separator", `the context was compacted (${item.tokens} tokens)`);
      break;
    case "reflection":
      bubble("separator", `the session was settled in the memory ($${(item.cost || 0).toFixed(5)})`);
      break;
    case "reverted":
      bubble("separator", `the conversation was rolled back to ${item.messages} messages`);
      break;
    case "session_switched":
      state.sessionId = item.session_id;
      break;
    default:
      break;
  }
  if (item.seq) state.seq = Math.max(state.seq, item.seq);
}

// -- the stream ------------------------------------------------------------

function openStream() {
  if (state.stream) state.stream.close();
  if (!state.sessionId) return;
  const stream = new EventSource(`/api/sessions/${state.sessionId}/stream?since=${state.seq}`);
  state.stream = stream;
  stream.onmessage = (event) => {
    const item = JSON.parse(event.data);
    render(item);
    if (item.kind === "turn_end" || item.kind === "command_end") {
      stream.close();
      state.stream = null;
      openStream();
      refreshStatus();
      loadSessions();
      loadChanges();
    }
  };
  stream.onerror = () => {
    stream.close();
    state.stream = null;
    setTimeout(openStream, 1000);
  };
}

// -- the state of the session ----------------------------------------------

async function refreshStatus() {
  if (!state.sessionId) return;
  try {
    const status = await api(`/api/sessions/${state.sessionId}/status`);
    document.getElementById("status").textContent =
      `${status.model} | ${status.tokens}/${status.window} | $${status.cost.toFixed(4)} | ${status.mode} | ${status.state}`;
    const fields = document.getElementById("status-fields");
    if (fields) {
      fields.innerHTML = "";
      for (const [key, value] of Object.entries(status)) {
        fields.appendChild(el("dt", "", key));
        fields.appendChild(el("dd", "", String(value)));
      }
    }
  } catch (error) {
    /* the session is gone; the next poll will say so */
  }
}

async function loadChanges() {
  const box = document.getElementById("changes");
  if (!box || !state.sessionId) return;
  try {
    const data = await api(`/api/sessions/${state.sessionId}/changes`);
    box.innerHTML = "";
    for (const change of data.changes) {
      box.appendChild(el("div", "", change.path));
      if (change.diff) box.appendChild(diffView(change.diff));
    }
  } catch (error) {
    /* no changes yet */
  }
}

// -- the sessions ----------------------------------------------------------

async function loadSessions() {
  const list = document.getElementById("sessions");
  if (!list) return;
  const data = await api("/api/sessions");
  list.innerHTML = "";
  for (const session of data.sessions) {
    const item = el("li", "", `${session.id}  ${session.turns}t  $${session.cost.toFixed(4)}`);
    item.title = session.cwd;
    if (session.id === state.sessionId) item.classList.add("active");
    item.onclick = () => openSession(session.id);
    list.appendChild(item);
  }
}

async function openSession(id) {
  state.sessionId = id;
  state.seq = 0;
  state.cards = {};
  state.assistant = null;
  document.getElementById("messages").innerHTML = "";
  const data = await api(`/api/sessions/${id}/items`);
  for (const item of data.items) render(item);
  openStream();
  refreshStatus();
  loadSessions();
  loadChanges();
}

// -- the files -------------------------------------------------------------

async function listFiles(path) {
  const list = document.getElementById("files");
  const data = await api(`/api/files?path=${encodeURIComponent(path)}&depth=1`);
  list.innerHTML = "";
  for (const entry of data.entries) {
    const item = el("li", entry.is_dir ? "dir" : "", entry.name + (entry.is_dir ? "/" : ""));
    item.onclick = () => {
      if (entry.is_dir) {
        listFiles(entry.path);
      } else {
        showFile(entry.path);
      }
    };
    list.appendChild(item);
  }
}

async function showFile(path) {
  const view = document.getElementById("file-view");
  try {
    const file = await api(`/api/file?path=${encodeURIComponent(path)}`);
    view.textContent = file.content;
  } catch (error) {
    view.textContent = `error: ${error.message}`;
  }
  try {
    const data = await api(`/api/diff?path=${encodeURIComponent(path)}`);
    if (data.diff) view.textContent += `\n\n--- diff ---\n${data.diff}`;
  } catch (error) {
    /* no diff */
  }
}

// -- the commands ----------------------------------------------------------

async function loadCommands() {
  const select = document.getElementById("command-list");
  if (!select) return;
  const data = await api("/api/commands");
  select.innerHTML = "";
  for (const command of data.commands) {
    const option = el("option", "", `/${command.name}`);
    option.value = `/${command.name}`;
    option.title = command.description;
    select.appendChild(option);
  }
}

// -- the wiring ------------------------------------------------------------

function wire() {
  const newSession = document.getElementById("new-session");
  if (newSession) {
    newSession.onclick = async () => {
      const data = await api("/api/sessions", { method: "POST" });
      await openSession(data.id);
    };
  }

  const composer = document.getElementById("composer");
  if (composer) {
    composer.onsubmit = async (event) => {
      event.preventDefault();
      const input = document.getElementById("input");
      const text = input.value.trim();
      if (!text || !state.sessionId) return;
      input.value = "";
      try {
        await api(`/api/sessions/${state.sessionId}/messages`, { method: "POST", body: { text } });
      } catch (error) {
        bubble("error", error.message);
      }
    };
  }

  const runCommand = document.getElementById("run-command");
  if (runCommand) {
    runCommand.onclick = () => {
      const input = document.getElementById("input");
      const select = document.getElementById("command-list");
      input.value = select.value;
      document.getElementById("composer").requestSubmit();
    };
  }

  const interrupt = document.getElementById("interrupt");
  if (interrupt) {
    interrupt.onclick = async () => {
      if (state.sessionId) await api(`/api/sessions/${state.sessionId}/interrupt`, { method: "POST" });
    };
  }

  const listButton = document.getElementById("list-files");
  if (listButton) {
    listButton.onclick = () => {
      const path = document.getElementById("file-path").value || ".";
      listFiles(path).catch((error) => bubble("error", error.message));
    };
  }
}

// -- the settings ----------------------------------------------------------

function parseKeyValues(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object") return parsed;
  } catch (error) {
    /* not json, so it is a list of `key: value` lines */
  }
  const result = {};
  for (const line of trimmed.split("\n")) {
    const index = line.indexOf(":");
    if (index < 0) continue;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (!key) continue;
    try {
      result[key] = JSON.parse(value);
    } catch (error) {
      result[key] = value;
    }
  }
  return result;
}

function formatKeyValues(object) {
  return Object.entries(object || {})
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("\n");
}

async function startSettings() {
  const data = await api("/api/config");
  const model = data.model;
  document.getElementById("config-path").textContent = data.user_config_path;
  document.getElementById("model-name").value = model.model_name || "";
  document.getElementById("api-base").value = model.api_base || "";
  document.getElementById("api-key").placeholder = model.api_key_set
    ? `set (${model.api_key_hint}) — type to replace`
    : "not set";
  document.getElementById("max-retries").value = model.max_retries;
  document.getElementById("set-cache-control").value = model.set_cache_control || "";
  document.getElementById("routing").value = formatKeyValues(model.routing);
  document.getElementById("routing-rules").value = (model.routing_rules || [])
    .map((rule) => `${rule.when}: ${rule.purpose}`)
    .join("\n");
  document.getElementById("model-kwargs").value = formatKeyValues(model.model_kwargs);

  for (const [field, source] of Object.entries(data.sources || {})) {
    const node = document.getElementById(`source-${field}`);
    if (node) node.textContent = `from: ${source}`;
  }

  const body = document.querySelector("#layers tbody");
  if (body) {
    body.innerHTML = "";
    for (const layer of data.layers || []) {
      const row = el("tr");
      row.appendChild(el("td", "", layer.layer));
      const cell = el("td");
      cell.appendChild(el("pre", "", JSON.stringify(layer.model, null, 2)));
      row.appendChild(cell);
      body.appendChild(row);
    }
  }

  const message = document.getElementById("config-message");
  const payload = () => ({
    model_name: document.getElementById("model-name").value.trim(),
    api_base: document.getElementById("api-base").value.trim(),
    api_key: document.getElementById("api-key").value,
    max_retries: Number(document.getElementById("max-retries").value || 0),
    set_cache_control: document.getElementById("set-cache-control").value,
    routing: parseKeyValues(document.getElementById("routing").value),
    routing_rules: Object.entries(parseKeyValues(document.getElementById("routing-rules").value)).map(
      ([when, purpose]) => ({ when, purpose })
    ),
    model_kwargs: parseKeyValues(document.getElementById("model-kwargs").value),
  });

  document.getElementById("model-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const answer = await api("/api/config/model", { method: "PUT", body: payload() });
      message.textContent = `saved to ${answer.path}`;
      document.getElementById("api-key").value = "";
      startSettings();
    } catch (error) {
      message.textContent = `error: ${error.message}`;
    }
  };

  document.getElementById("test-connection").onclick = async () => {
    message.textContent = "trying…";
    try {
      const answer = await api("/api/config/model/test", { method: "POST", body: payload() });
      message.textContent = answer.ok
        ? `ok: ${answer.latency_ms}ms, $${(answer.cost || 0).toFixed(6)}`
        : `error: ${answer.error}`;
    } catch (error) {
      message.textContent = `error: ${error.message}`;
    }
  };
}

async function start() {
  wire();
  await loadCommands().catch(() => {});
  await loadSessions().catch(() => {});
  const data = await api("/api/sessions", { method: "POST" });
  await openSession(data.id);
  setInterval(refreshStatus, 2000);
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("messages")) start();
  if (document.getElementById("model-form")) startSettings();
});
