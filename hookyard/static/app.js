const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const binEl = document.getElementById("bin");
const urlEl = document.getElementById("url");
const searchEl = document.getElementById("search");
const methodEl = document.getElementById("method");
const emptyEl = document.getElementById("empty");

let selectedId = null;
let selectedPreset = null;
let presets = [];
let currentItems = [];
let searchTimer = 0;
let loadSeq = 0;

function binId() {
  return binEl.value.trim() || "demo";
}

function authHeaders() {
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${location.host}/ws${q}`;
}

function refreshUrl() {
  urlEl.textContent = `${location.origin}/b/${binId()}`;
}

function filterQuery() {
  const params = new URLSearchParams();
  const q = searchEl.value.trim();
  if (q) params.set("q", q);
  if (methodEl.value) params.set("method", methodEl.value);
  const suffix = params.toString();
  return suffix ? `?${suffix}` : "";
}

async function loadBin() {
  refreshUrl();
  const seq = ++loadSeq;
  await fetch("/api/bins", {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify({ id: binId() }),
  });
  const res = await fetch(
    `/api/bins/${encodeURIComponent(binId())}${filterQuery()}`,
    { headers: authHeaders() },
  );
  if (seq !== loadSeq) return;
  const data = await res.json();
  renderList(data.requests || []);
}

function renderList(items) {
  currentItems = items;
  listEl.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    const method = document.createElement("span");
    method.className = "method";
    method.textContent = item.method;
    const path = document.createTextNode(item.path);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = new Date(item.created_at * 1000).toLocaleTimeString();
    li.append(method, path, meta);
    if (item.id === selectedId) li.classList.add("active");
    li.onclick = () => {
      selectedId = item.id;
      for (const row of listEl.children) row.classList.toggle("active", row === li);
      show(item.id);
    };
    listEl.appendChild(li);
  }
  const filtering = Boolean(searchEl.value.trim() || methodEl.value);
  emptyEl.hidden = items.length > 0;
  emptyEl.textContent = filtering
    ? "No requests match your filters."
    : "No requests yet. POST a webhook to the catch URL.";
}

async function show(id) {
  selectedId = id;
  selectedPreset = null;
  const res = await fetch(`/api/bins/${encodeURIComponent(binId())}/${encodeURIComponent(id)}`, {
    headers: authHeaders(),
  });
  const item = await res.json();
  const sigs = Object.entries(item.signatures || {})
    .map(([k, v]) => `<span class="sig ${v ? "ok" : "bad"}">${escapeHtml(k)}: ${v ? "valid" : "invalid"}</span>`)
    .join("");
  const headers = Object.entries(item.headers)
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
  detailEl.innerHTML = `
    <h2></h2>
    <p class="meta"></p>
    <div class="sigs">${sigs}</div>
    <h3>Compare</h3>
    <div class="row">
      <select id="diff-target" aria-label="Compare with request" style="flex:1"></select>
      <button id="diff" class="ghost">Diff</button>
    </div>
    <pre id="diff-out"></pre>
    <h3>Headers</h3>
    <pre class="headers"></pre>
    <h3>Body</h3>
    <pre class="body"></pre>
    <h3>Replay</h3>
    <div class="row">
      <select id="preset" aria-label="Replay preset" style="flex:1">
        <option value="">Custom target</option>
      </select>
    </div>
    <div class="row">
      <input id="target" placeholder="http://127.0.0.1:3000/webhook" style="flex:1">
      <button id="replay">Replay</button>
    </div>
    <p id="openapi-note" class="hint"></p>
    <pre id="replay-out"></pre>
  `;
  detailEl.querySelector("h2").textContent = `${item.method} ${item.path}`;
  detailEl.querySelector(".meta").textContent = `${item.id} · ${item.size} bytes · ${item.remote}`;
  detailEl.querySelector(".headers").textContent = headers;
  detailEl.querySelector(".body").textContent = item.pretty || item.body || "";
  renderPresets();
  renderDiffOptions(id);
  document.getElementById("replay").onclick = async () => {
    const target = document.getElementById("target").value;
    const body = selectedPreset ? { preset: selectedPreset } : { target };
    const out = await fetch(`/api/bins/${encodeURIComponent(binId())}/${encodeURIComponent(id)}/replay`, {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    document.getElementById("replay-out").textContent = JSON.stringify(await out.json(), null, 2);
  };
  suggestOpenApi(id);
}

function renderPresets() {
  const select = document.getElementById("preset");
  const targetEl = document.getElementById("target");
  if (!select || !targetEl) return;
  for (const preset of presets) {
    const option = document.createElement("option");
    option.value = preset.name;
    option.textContent = preset.sign
      ? `${preset.name} · signed: ${preset.sign}`
      : preset.name;
    select.appendChild(option);
  }
  select.hidden = presets.length === 0;
  select.onchange = () => {
    const preset = presets.find((entry) => entry.name === select.value);
    if (!preset) {
      selectedPreset = null;
      return;
    }
    selectedPreset = preset.name;
    targetEl.value = preset.target;
  };
  targetEl.oninput = () => {
    if (!selectedPreset) return;
    selectedPreset = null;
    select.value = "";
  };
}

async function loadPresets() {
  try {
    const res = await fetch("/api/presets", { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    presets = Array.isArray(data.presets) ? data.presets : [];
  } catch {
    presets = [];
  }
}

function renderDiffOptions(id) {
  const select = document.getElementById("diff-target");
  const button = document.getElementById("diff");
  if (!select || !button) return;
  for (const item of currentItems) {
    if (item.id === id) continue;
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.method} ${item.path} · ${new Date(item.created_at * 1000).toLocaleTimeString()}`;
    select.appendChild(option);
  }
  button.disabled = select.options.length === 0;
  if (select.options.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No other requests to compare";
    select.appendChild(option);
  }
  button.onclick = async () => {
    if (!select.value) return;
    const out = document.getElementById("diff-out");
    const res = await fetch(
      `/api/bins/${encodeURIComponent(binId())}/diff?left=${encodeURIComponent(id)}&right=${encodeURIComponent(select.value)}`,
      { headers: authHeaders() },
    );
    out.textContent = JSON.stringify(await res.json(), null, 2);
  };
}

async function suggestOpenApi(id) {
  let data;
  try {
    const res = await fetch(
      `/api/bins/${encodeURIComponent(binId())}/${encodeURIComponent(id)}/openapi`,
      { headers: authHeaders() },
    );
    if (!res.ok) return;
    data = await res.json();
  } catch {
    return;
  }
  if (selectedId !== id || !data.matched) return;
  const targetEl = document.getElementById("target");
  const noteEl = document.getElementById("openapi-note");
  if (!targetEl || !noteEl) return;
  const op = data.operation || {};
  noteEl.textContent = `OpenAPI: ${op.operation_id || `${op.method} ${op.path}`}`;
  if (!targetEl.value && data.target) targetEl.value = data.target;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

document.getElementById("create").onclick = () => {
  selectedId = null;
  selectedPreset = null;
  loadBin();
};
document.getElementById("clear").onclick = async () => {
  await fetch(`/api/bins/${encodeURIComponent(binId())}`, { method: "DELETE", headers: authHeaders() });
  selectedId = null;
  selectedPreset = null;
  detailEl.innerHTML = '<p class="empty">Waiting for webhooks…</p>';
  await loadBin();
};

searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadBin, 200);
});
methodEl.addEventListener("change", loadBin);

const ws = new WebSocket(wsUrl());
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "request" && msg.record.bin_id === binId()) loadBin();
};

async function init() {
  await loadPresets();
  refreshUrl();
  await loadBin();
}

init();
