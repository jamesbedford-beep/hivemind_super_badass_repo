const $ = (s) => document.querySelector(s);
const api = async (path, body) => {
  const r = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {});
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
};

let SUGGESTIONS = [], BLOCKED = [], MANIFEST = { documents: [], excluded: [] };

function show(n) {
  document.querySelectorAll(".step").forEach((s, i) => s.classList.toggle("on", i === n));
  document.querySelectorAll("nav button").forEach((b, i) => b.classList.toggle("on", i === n));
  if (n === 2) refreshReview();
}
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => show(+b.dataset.s)));

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function rowHtml(f, checked) {
  return `<label class="row"><input type="checkbox" value="${esc(f.path)}" ${checked ? "checked" : ""}>
    <span style="flex:1"><span class="nm">${esc(f.name || f.path.split("\\").pop())}</span>
    <span class="pth">${esc(f.path)}</span>
    ${f.reason ? `<span class="why">${esc(f.reason)}</span>` : ""}</span>
    ${f.score !== undefined ? `<span class="badge">${f.score}</span>` : ""}</label>`;
}

function renderSuggestions() {
  const q = ($("#filter").value || "").toLowerCase();
  const inVault = new Set(MANIFEST.documents.map((d) => d.path));
  const list = SUGGESTIONS.filter((f) => !inVault.has(f.path) &&
    (!q || f.path.toLowerCase().includes(q)));
  $("#sugList").innerHTML = list.slice(0, 300).map((f) => rowHtml(f)).join("") ||
    '<div class="row muted">nothing left to suggest</div>';
  $("#sugCount").textContent = `${list.length} available`;
}

function renderVault() {
  $("#vaultList").innerHTML = MANIFEST.documents.map((d) =>
    rowHtml({ path: d.path, name: d.path.split("\\").pop(), reason: d.added_by })).join("") ||
    '<div class="row muted">empty</div>';
  $("#vaultCount").textContent = `${MANIFEST.documents.length} documents`;
}

$("#filter").addEventListener("input", renderSuggestions);

// ---- connect
async function refreshState() {
  const s = await api("/api/state");
  $("#vaultPath").textContent = s.vault;
  MANIFEST = s.manifest;
  $("#remoteList").innerHTML = s.remotes.length
    ? `existing remotes: ${s.remotes.map((r) => `<code>${esc(r)}</code>`).join(", ")}`
    : "no Google account connected yet";
  if (s.remotes.length && !$("#remoteName").value) $("#remoteName").value = s.remotes[0];
  renderVault();
}

$("#btnConnect").addEventListener("click", async () => {
  const remote = $("#remoteName").value.trim() || "gdrive";
  $("#connectMsg").textContent = "a browser window will open, approve access there…";
  try {
    await api("/api/connect", { remote });
    $("#connectMsg").textContent = "connected";
    await refreshState();
    await loadDrives(remote);
  } catch (e) { $("#connectMsg").textContent = "failed: " + e.message; }
});

async function loadDrives(remote) {
  try {
    const d = await api("/api/drives", { remote });
    $("#drives").innerHTML = d.drives.map((x, i) =>
      `<label class="chk"><input type="checkbox" class="scope" data-id="${x.id || ""}"
        data-name="${esc(x.name)}" ${i === 0 ? "checked" : ""}> ${esc(x.name)}</label>`).join("");
    $("#btnScan").disabled = false;
  } catch (e) { $("#drives").textContent = "could not list drives: " + e.message; }
}

$("#btnScan").addEventListener("click", async () => {
  const scopes = [...document.querySelectorAll(".scope:checked")].map((c) =>
    ({ id: c.dataset.id || null, name: c.dataset.name }));
  if (!scopes.length) return ($("#scanMsg").textContent = "pick at least one scope");
  $("#scanMsg").textContent = "scanning Drive, this can take a minute…";
  $("#btnScan").disabled = true;
  try {
    const r = await api("/api/scan", { scopes });
    SUGGESTIONS = r.suggestions; BLOCKED = r.blocked;
    $("#scanMsg").textContent = `${r.total} files found, ${r.suggestions.length} ranked, ${r.blocked.length} blocked as sensitive`;
    renderSuggestions(); renderVault(); show(1);
  } catch (e) { $("#scanMsg").textContent = "scan failed: " + e.message; }
  $("#btnScan").disabled = false;
});

// ---- curate
async function addPaths(paths, reason) {
  if (!paths.length) return;
  await api("/api/add", { paths, reason });
  MANIFEST = (await api("/api/state")).manifest;
  renderSuggestions(); renderVault();
}
$("#btnTop25").addEventListener("click", () => {
  const inVault = new Set(MANIFEST.documents.map((d) => d.path));
  addPaths(SUGGESTIONS.filter((f) => !inVault.has(f.path)).slice(0, 25).map((f) => f.path), "suggestion:top-ranked");
});
$("#btnAddSel").addEventListener("click", () =>
  addPaths([...document.querySelectorAll("#sugList input:checked")].map((c) => c.value), "manual"));
$("#btnRmSel").addEventListener("click", async () => {
  const paths = [...document.querySelectorAll("#vaultList input:checked")].map((c) => c.value);
  if (!paths.length) return;
  await api("/api/remove", { paths });
  MANIFEST = (await api("/api/state")).manifest;
  renderSuggestions(); renderVault();
});

// ---- review
async function refreshReview() {
  const r = await api("/api/review", { emails: [] });
  const e = r.estimate;
  $("#estStat").innerHTML =
    `<div><span>${e.documents}</span><small>documents</small></div>
     <div><span>${e.mb} MB</span><small>source text</small></div>
     <div><span>~${(e.est_tokens / 1e6).toFixed(1)}M</span><small>estimated tokens</small></div>
     <div><span>~${e.est_hours}h</span><small>estimated build</small></div>`;
  const ex = r.excluded || [];
  $("#sensBox").innerHTML = ex.length
    ? `<div class="warn"><strong>${ex.length} document${ex.length > 1 ? "s" : ""} blocked as personal data.</strong>
        <div class="muted" style="margin-top:.4rem">Kept out regardless of who can access the original.</div>
        <ul style="margin:.5rem 0 0;padding-left:1.1rem;font-size:.8rem">
        ${ex.slice(0, 12).map((x) => `<li>${esc(x.path.split("\\").pop())} <em>${esc(x.reason)}</em></li>`).join("")}
        </ul></div>`
    : `<div class="ok">No personal data detected in the current selection.</div>`;
}

$("#btnPreview").addEventListener("click", async () => {
  const emails = $("#emails").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!emails.length) return;
  $("#previewOut").textContent = "checking real Drive permissions…";
  try {
    const r = await api("/api/review", { emails });
    $("#previewOut").innerHTML = r.access_preview.map((p) =>
      `<div class="row"><span style="flex:1"><span class="nm">${esc(p.email)}</span>
        <span class="why">${p.accessible} of ${p.sample} sampled documents</span></span>
        <span class="badge">${p.pct}%</span></div>`).join("");
  } catch (e) { $("#previewOut").textContent = "failed: " + e.message; }
});

// ---- build
$("#btnBuild").addEventListener("click", async () => {
  $("#buildMsg").textContent = "starting…";
  try {
    await api("/api/build", {});
    poll();
  } catch (e) { $("#buildMsg").textContent = e.message; }
});
async function poll() {
  const s = await api("/api/build/status");
  $("#buildLog").textContent = (s.log || []).join("\n") || "…";
  $("#buildMsg").textContent = s.running ? "running" : (s.error ? "failed" : (s.done ? "done" : ""));
  if (s.running) setTimeout(poll, 1500);
}

// ---- ship
$("#btnShip").addEventListener("click", async () => {
  $("#shipOut").textContent = "packaging…";
  try {
    const r = await api("/api/ship", {});
    $("#shipOut").innerHTML = `<div class="ok"><strong>Bundle ready</strong>
      <div class="muted" style="margin-top:.3rem">${esc(r.bundle)}</div>
      <div style="margin-top:.5rem">${r.notes} notes included.</div></div>
      <pre style="margin-top:.7rem">${esc(r.message)}</pre>`;
  } catch (e) { $("#shipOut").textContent = "failed: " + e.message; }
});

refreshState();
