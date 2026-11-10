const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const binEl = document.getElementById("bin");
const urlEl = document.getElementById("url");
const searchEl = document.getElementById("search");
const methodEl = document.getElementById("method");
const emptyEl = document.getElementById("empty");

let selectedId = null;
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
    <h3>Headers</h3>
    <pre class="headers"></pre>
    <h3>Body</h3>
    <pre class="body"></pre>
    <h3>Replay</h3>
    <div class="row">
      <input id="target" placeholder="http://127.0.0.1:3000/webhook" style="flex:1">
      <button id="replay">Replay</button>
    </div>
    <pre id="replay-out"></pre>
  `;
  detailEl.querySelector("h2").textContent = `${item.method} ${item.path}`;
  detailEl.querySelector(".meta").textContent = `${item.id} · ${item.size} bytes · ${item.remote}`;
  detailEl.querySelector(".headers").textContent = headers;
  detailEl.querySelector(".body").textContent = item.pretty || item.body || "";
  document.getElementById("replay").onclick = async () => {
    const target = document.getElementById("target").value;
    const out = await fetch(`/api/bins/${encodeURIComponent(binId())}/${encodeURIComponent(id)}/replay`, {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify({ target }),
    });
    document.getElementById("replay-out").textContent = JSON.stringify(await out.json(), null, 2);
  };
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
  loadBin();
};
document.getElementById("clear").onclick = async () => {
  await fetch(`/api/bins/${encodeURIComponent(binId())}`, { method: "DELETE", headers: authHeaders() });
  selectedId = null;
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

refreshUrl();
loadBin();
