const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const binEl = document.getElementById("bin");
const urlEl = document.getElementById("url");

function binId() {
  return binEl.value.trim() || "demo";
}

function refreshUrl() {
  urlEl.textContent = `${location.origin}/b/${binId()}`;
}

async function loadBin() {
  refreshUrl();
  await fetch("/api/bins", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id: binId() }),
  });
  const res = await fetch(`/api/bins/${binId()}`);
  const data = await res.json();
  renderList(data.requests || []);
}

function renderList(items) {
  listEl.innerHTML = "";
  for (const item of items) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="method">${item.method}</span>${item.path}<div class="meta">${new Date(item.created_at * 1000).toLocaleTimeString()}</div>`;
    li.onclick = () => show(item.id);
    listEl.appendChild(li);
  }
}

async function show(id) {
  const res = await fetch(`/api/bins/${binId()}/${id}`);
  const item = await res.json();
  const sigs = Object.entries(item.signatures || {})
    .map(([k, v]) => `<span class="sig ${v ? "ok" : "bad"}">${k}: ${v ? "valid" : "invalid"}</span>`)
    .join("");
  const headers = Object.entries(item.headers)
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
  detailEl.innerHTML = `
    <h2>${item.method} ${item.path}</h2>
    <p class="meta">${item.id} · ${item.size} bytes · ${item.remote}</p>
    <div>${sigs}</div>
    <h3>Headers</h3>
    <pre>${escapeHtml(headers)}</pre>
    <h3>Body</h3>
    <pre>${escapeHtml(item.pretty || item.body || "")}</pre>
    <h3>Replay</h3>
    <div class="row">
      <input id="target" placeholder="http://localhost:3000/webhook" style="flex:1">
      <button id="replay">Replay</button>
    </div>
    <pre id="replay-out"></pre>
  `;
  document.getElementById("replay").onclick = async () => {
    const target = document.getElementById("target").value;
    const out = await fetch(`/api/bins/${binId()}/${id}/replay`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ target }),
    });
    document.getElementById("replay-out").textContent = JSON.stringify(await out.json(), null, 2);
  };
}

function escapeHtml(value) {
  return value.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

document.getElementById("create").onclick = loadBin;
document.getElementById("clear").onclick = async () => {
  await fetch(`/api/bins/${binId()}`, { method: "DELETE" });
  await loadBin();
};

const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "request" && msg.record.bin_id === binId()) loadBin();
};

refreshUrl();
loadBin();
