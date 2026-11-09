"use strict";

const CLIENT = { "X-Coder-Client": "1" };

/* The strings of the language of the page. The template hands them over. */
function t(key, values = {}) {
  const text = (window.STRINGS || {})[key] || key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in values ? values[name] : match));
}

const MODE_NOTES = {
  default: "mode_default",
  acceptEdits: "mode_acceptEdits",
  plan: "mode_plan",
  readonly: "mode_readonly",
  bypass: "mode_bypass",
};

const state = {
  sessionId: null,
  seq: 0,
  stream: null,
  cards: {},
  assistant: null,
  current: null,
  stick: true,
  mode: "",
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

function messages() {
  return document.getElementById("messages");
}

/* The items of the turn that is running. The turns before it are folded away. */
function target() {
  if (!state.current) {
    state.current = el("div", "turn");
    messages().appendChild(state.current);
  }
  return state.current;
}

function foldTurn() {
  const done = state.current;
  state.current = null;
  if (!done) return;
  let history = document.getElementById("history");
  if (!history) {
    history = el("details", "history");
    history.id = "history";
    history.appendChild(el("summary", "", t("history")));
    history.appendChild(el("div", "history-body"));
    messages().insertBefore(history, messages().firstChild);
  }
  history.querySelector(".history-body").appendChild(done);
  const count = history.querySelectorAll(".turn").length;
  history.querySelector("summary").textContent = t("earlier_turns", { count });
}

/* The conversation follows the newest content, unless the user scrolled up. */
function scrollToBottom(force) {
  const box = messages();
  if (force || state.stick) box.scrollTop = box.scrollHeight;
}

function bubble(className, text) {
  const node = el("div", `bubble ${className}`, text || "");
  target().appendChild(node);
  scrollToBottom();
  return node;
}

function toolCard(item) {
  const card = el("div", "tool");
  const header = el("header");
  header.appendChild(el("strong", "", item.tool || t("tool")));
  if (item.summary) header.appendChild(el("span", "", item.summary));
  card.appendChild(header);
  const body = el("div", "body", t("running"));
  card.appendChild(body);
  target().appendChild(card);
  scrollToBottom();
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
  header.appendChild(el("strong", "", t("approval", { tool: item.tool })));
  if (item.reason) header.appendChild(el("span", "", item.reason));
  card.appendChild(header);
  const body = el("div", "body", JSON.stringify(item.params || {}, null, 2));
  card.appendChild(body);
  const buttons = el("div", "buttons");
  for (const [label, decision] of [[t("allow"), "allow"], [t("deny"), "deny"], [t("always"), "always"]]) {
    const button = el("button", decision === "allow" ? "primary" : "", label);
    button.onclick = async () => {
      buttons.innerHTML = "";
      buttons.appendChild(el("span", "", t("answered")));
      try {
        await api(`/api/approvals/${item.id}`, { method: "POST", body: { decision } });
      } catch (error) {
        buttons.appendChild(el("span", "", t("error", { message: error.message })));
      }
    };
    buttons.appendChild(button);
  }
  card.appendChild(buttons);
  target().appendChild(card);
  scrollToBottom();
  return card;
}

function renderTodos(todos) {
  const turn = target();
  let panel = turn.querySelector(".todos");
  if (!panel) {
    panel = el("div", "todos");
    turn.appendChild(panel);
  }
  panel.innerHTML = "";
  for (const todo of todos || []) {
    panel.appendChild(el("div", todo.status === "completed" ? "done" : "", todo.content || ""));
  }
}

function render(item) {
  switch (item.kind) {
    case "user_message":
      foldTurn();
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
      scrollToBottom();
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
          el("span", "", item.timed_out ? t("no_answer") : t("answered_decision", { decision: item.decision }))
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
      bubble("separator", t("compacted", { tokens: item.tokens }));
      break;
    case "reflection":
      bubble("separator", t("settled", { cost: (item.cost || 0).toFixed(5) }));
      break;
    case "reverted":
      bubble("separator", t("rolled_back", { messages: item.messages }));
      break;
    case "session_switched":
      state.sessionId = item.session_id;
      break;
    case "mode_changed":
      refreshStatus();
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
        fields.appendChild(el("dt", "", t(`field_${key}`)));
        fields.appendChild(el("dd", "", String(value)));
      }
    }
    showMode(status.mode);
  } catch (error) {
    /* the session is gone; the next poll will say so */
  }
}

/* The mode of the session, in the inspector of the chat page. */
function showMode(mode) {
  if (!mode) return;
  state.mode = mode;
  const select = document.getElementById("permission-mode");
  /* The user may be picking a mode: the poll must not pull the box away. */
  if (select && select.value !== mode && document.activeElement !== select) select.value = mode;
  const note = document.getElementById("mode-note");
  if (note) note.textContent = t(MODE_NOTES[mode] || "");
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
  state.current = null;
  messages().innerHTML = "";
  const data = await api(`/api/sessions/${id}/items`);
  for (const item of data.items) render(item);
  scrollToBottom(true);
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
    view.textContent = t("error", { message: error.message });
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

// -- the language -----------------------------------------------------------

const LANGUAGE_KEY = "coder_lang";

/* The text of a language, without leaving the page: the page of that language
   is fetched and put in place, and the strings of the browser are replaced. */
async function switchLanguage(code) {
  const data = await api(`/api/i18n/${encodeURIComponent(code)}`);
  window.STRINGS = data.strings;
  const answer = await fetch(`${location.pathname}?lang=${encodeURIComponent(code)}`);
  const doc = new DOMParser().parseFromString(await answer.text(), "text/html");
  document.title = doc.title;
  document.documentElement.lang = doc.documentElement.lang;
  const fresh = doc.body.cloneNode(true);
  fresh.querySelectorAll("script").forEach((node) => node.remove());
  document.body.replaceChildren(...fresh.childNodes);
  /* The choice is kept in the browser and in the cookie: the server renders the
     right language the next time, and the browser finds its choice again. */
  document.cookie = `${LANGUAGE_KEY}=${code}; path=/; max-age=31536000; samesite=lax`;
  localStorage.setItem(LANGUAGE_KEY, code);
}

/* The values of the form, so that a change of the language does not throw
   away what was typed. */
function formValues() {
  const values = {};
  for (const node of document.querySelectorAll("input, textarea, select")) {
    if (node.type !== "password" && node.id) values[node.id] = node.value;
  }
  return values;
}

function restoreForm(values) {
  for (const [id, value] of Object.entries(values)) {
    const node = document.getElementById(id);
    if (node) node.value = value;
  }
}

/* The page is drawn again in the new language: the conversation is read from
   the log, the settings are read from the configuration. The values of the
   form are the ones of before the switch, so nothing that was typed is lost. */
async function relocalize(values = {}) {
  if (document.getElementById("messages")) {
    wire();
    await loadCommands().catch(() => {});
    if (state.sessionId) await openSession(state.sessionId);
    return;
  }
  if (!document.getElementById("model-form")) return;
  await startSettings();
  restoreForm(values);
}

async function chooseLanguage(code) {
  try {
    const values = formValues();
    await switchLanguage(code);
    await relocalize(values);
  } catch (error) {
    /* the page stays in the language it has */
  }
}

// -- the wiring ------------------------------------------------------------

function wire() {
  const box = messages();
  if (box) {
    box.addEventListener("scroll", () => {
      const gap = box.scrollHeight - box.scrollTop - box.clientHeight;
      state.stick = gap < 40;
    });
  }

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

  const modeSelect = document.getElementById("permission-mode");
  if (modeSelect) {
    modeSelect.onchange = async () => {
      const mode = modeSelect.value;
      const previous = state.mode;
      if (!state.sessionId) {
        modeSelect.value = previous || "default";
        return;
      }
      try {
        await api(`/api/sessions/${state.sessionId}/mode`, { method: "POST", body: { mode } });
        showMode(mode);
      } catch (error) {
        modeSelect.value = previous || "default";
        bubble("error", error.message);
      }
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

function splitLines(text) {
  return (text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function renderTest(answer, target = "model-test") {
  // What the test found out: the settings, the file, the call and the tools.
  const box = document.getElementById(target);
  box.innerHTML = "";
  const resolved = answer.resolved || {};
  const file = answer.file || {};
  const tools = answer.tools || {};
  let fileText;
  if (file.ok) {
    fileText = `${file.path || "none"}${file.aliases && file.aliases.length ? ` — ${file.aliases.join(", ")}` : ""}`;
  } else if ((file.error || "").includes("not one of the aliases")) {
    fileText = `${file.path || "none"} — ${t("not_an_alias")}`;
  } else {
    fileText = `${file.path || "none"} — ${file.error}`;
  }
  const rows = [
    [t("row_model"), `${resolved.model_name || "?"}${resolved.alias ? ` (alias ${resolved.alias})` : ""}`],
    [t("row_api_base"), resolved.api_base || t("not_set")],
    [t("row_api_key"), resolved.api_key_set ? `set (${resolved.api_key_hint})` : t("not_set")],
    [t("row_aliases"), fileText],
    [t("row_tools"), tools.ok ? t("tools_ok") : tools.error || t("not_tried")],
  ];
  const list = el("dl");
  for (const [key, value] of rows) {
    list.appendChild(el("dt", "", key));
    list.appendChild(el("dd", "", value));
  }
  box.appendChild(list);
}

function wireApiKey(input, placeholder, note) {
  // A click shows the key of the settings, a second click hides it again.
  let revealed = false;
  input.onclick = async () => {
    if (revealed) {
      revealed = false;
      input.value = "";
      input.type = "password";
      input.placeholder = placeholder();
      return;
    }
    if (input.value.trim()) return;
    // A key that is being typed is left alone.
    try {
      const answer = await api("/api/config/model/key");
      if (!answer.api_key) {
        if (note) note.textContent = t("no_key");
        return;
      }
      input.value = answer.api_key;
      input.type = "text";
      input.select();
      revealed = true;
    } catch (error) {
      if (note) note.textContent = t("error", { message: error.message });
    }
  };
}

async function startSettings() {
  const data = await api("/api/config");
  const model = data.model;
  const permissions = data.permissions || {};
  document.getElementById("config-path").textContent = data.user_config_path;
  document.getElementById("model-name").value = model.model_name || "";
  document.getElementById("litellm-config").value = model.litellm_config || "";
  document.getElementById("api-base").value = model.api_base || "";
  document.getElementById("max-retries").value = model.max_retries;
  document.getElementById("set-cache-control").value = model.set_cache_control || "";
  document.getElementById("routing").value = formatKeyValues(model.routing);
  document.getElementById("routing-rules").value = (model.routing_rules || [])
    .map((rule) => `${rule.when}: ${rule.purpose}`)
    .join("\n");
  document.getElementById("model-kwargs").value = formatKeyValues(model.model_kwargs);

  document.getElementById("permission-mode").value = permissions.mode || "default";
  document.getElementById("deny-paths").value = (permissions.deny_paths || []).join("\n");
  document.getElementById("include-dirs").value = (permissions.include_dirs || []).join("\n");
  const permissionSource = document.getElementById("source-mode");
  if (permissionSource) {
    permissionSource.textContent = t("from", { source: (permissions.source || {}).mode || "defaults" });
  }
  const serverNote = document.getElementById("server-mode-note");
  if (serverNote) {
    serverNote.textContent = permissions.server_mode
      ? t("server_mode", { mode: permissions.server_mode })
      : "";
  }

  for (const [field, source] of Object.entries(data.sources || {})) {
    const node = document.getElementById(`source-${field}`);
    if (node) node.textContent = t("from", { source });
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

  const keyInput = document.getElementById("api-key");
  keyInput.type = "password";
  keyInput.value = "";
  const keyPlaceholder = () =>
    model.api_key_set ? t("key_set", { hint: model.api_key_hint }) : t("key_not_set");
  keyInput.placeholder = keyPlaceholder();

  const message = document.getElementById("config-message");
  const payload = () => {
    const form = {
      model_name: document.getElementById("model-name").value.trim(),
      litellm_config: document.getElementById("litellm-config").value.trim(),
      api_base: document.getElementById("api-base").value.trim(),
      max_retries: Number(document.getElementById("max-retries").value || 0),
      set_cache_control: document.getElementById("set-cache-control").value,
      routing: parseKeyValues(document.getElementById("routing").value),
      routing_rules: Object.entries(parseKeyValues(document.getElementById("routing-rules").value)).map(
        ([when, purpose]) => ({ when, purpose })
      ),
      model_kwargs: parseKeyValues(document.getElementById("model-kwargs").value),
    };
    const key = keyInput.value.trim();
    if (key) form.api_key = key;
    return form;
  };

  wireApiKey(keyInput, keyPlaceholder, message);

  document.getElementById("model-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const answer = await api("/api/config/model", { method: "PUT", body: payload() });
      message.textContent = t("saved", { path: answer.path });
      document.getElementById("api-key").value = "";
      startSettings();
    } catch (error) {
      message.textContent = t("error", { message: error.message });
    }
  };

  document.getElementById("test-connection").onclick = async () => {
    message.textContent = t("trying");
    try {
      const answer = await api("/api/config/model/test", { method: "POST", body: payload() });
      message.textContent = answer.ok
        ? t("ok_ms", { ms: answer.latency_ms })
        : t("error", { message: answer.error });
      renderTest(answer);
    } catch (error) {
      message.textContent = t("error", { message: error.message });
    }
  };

  const testEndpoint = document.getElementById("test-endpoint");
  const testKey = document.getElementById("test-api-key");
  const testName = document.getElementById("test-model-name");
  const testNote = document.getElementById("test-message");
  testEndpoint.value = model.api_base || "";
  testName.value = model.model_name || "";
  testKey.type = "password";
  testKey.value = "";
  wireApiKey(testKey, () => t("key_of_endpoint"), testNote);

  document.getElementById("test-form").onsubmit = async (event) => {
    event.preventDefault();
    const body = { model_name: testName.value.trim() };
    if (body.model_name && !body.model_name.includes("/")) {
      // The endpoint is an OpenAI compatible one, so that is the provider.
      body.model_name = `openai/${body.model_name}`;
    }
    const endpoint = testEndpoint.value.trim();
    if (endpoint) body.api_base = endpoint;
    const key = testKey.value.trim();
    if (key) body.api_key = key;
    testNote.textContent = t("trying");
    try {
      const answer = await api("/api/config/model/test", { method: "POST", body });
      testNote.textContent = answer.ok ? t("ok_ms", { ms: answer.latency_ms }) : t("error", { message: answer.error });
      renderTest(answer, "test-result");
    } catch (error) {
      testNote.textContent = t("error", { message: error.message });
    }
  };

  document.getElementById("permissions-form").onsubmit = async (event) => {
    event.preventDefault();
    const note = document.getElementById("permissions-message");
    try {
      const answer = await api("/api/config/permissions", {
        method: "PUT",
        body: {
          mode: document.getElementById("permission-mode").value,
          deny_paths: splitLines(document.getElementById("deny-paths").value),
          include_dirs: splitLines(document.getElementById("include-dirs").value),
        },
      });
      note.textContent = t("saved", { path: answer.path });
      startSettings();
    } catch (error) {
      note.textContent = t("error", { message: error.message });
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

document.addEventListener("DOMContentLoaded", async () => {
  /* The language of the visitor is remembered in the browser: it wins over the
     one the server rendered, so a refresh does not change it back. */
  const saved = localStorage.getItem(LANGUAGE_KEY);
  if (saved && saved !== document.documentElement.lang) {
    await switchLanguage(saved).catch(() => {});
  }
  if (document.getElementById("messages")) start();
  if (document.getElementById("model-form")) startSettings();
});
