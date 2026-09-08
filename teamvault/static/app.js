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
// the Back / Continue buttons at the foot of each step drive the same routing,
// so the flow can be walked start to finish without using the tabs
document.querySelectorAll("[data-go]").forEach((b) =>
  b.addEventListener("click", () => show(+b.dataset.go)));

// ---- where the documents come from
let MODE = "drive";
let REMOTES = [];

function currentRemote() {
  const typed = ($("#remoteName").value || "").trim();
  return typed || ACCOUNT.remote || REMOTES[0] || "";
}

// ---- which Google account, said the way a person would say it
let ACCOUNT = { connected: false };

function renderAccount() {
  const one = ACCOUNT.connected
    ? `Signed in as <strong>${esc(ACCOUNT.email || ACCOUNT.remote)}</strong>`
    : "Not connected yet. This opens Google in your browser and asks for "
      + "read-only access to your Drive.";
  $("#acctLine").innerHTML = one;
  if ($("#acctLine2")) $("#acctLine2").innerHTML = one;
  $("#btnConnect").textContent = ACCOUNT.connected
    ? "Use a different account" : "Connect with Google";
}

async function loadAccount() {
  try {
    ACCOUNT = await api("/api/whoami", {});
  } catch (e) {
    ACCOUNT = { connected: false };
  }
  renderAccount();
}
let SOURCE_OK = false;   // a source has been validated and can be scanned

function setMode(mode) {
  MODE = mode;
  SOURCE_OK = false;
  document.querySelectorAll(".src").forEach((s) => s.classList.toggle("on", s.dataset.mode === mode));
  const pane = { drive: "paneDrive", folder: "paneFolder", local: "paneLocal" }[mode];
  document.querySelectorAll(".pane").forEach((s) => s.classList.toggle("on", s.id === pane));
  $("#btnScan").textContent =
    mode === "drive" ? "Scan selected drives"
      : mode === "folder" ? "Read this folder" : "Read this folder";
  // a local folder needs no Google account, so nothing gates it but the path
  $("#btnScan").disabled = true;
  $("#scanMsg").textContent = "";
}
document.querySelectorAll(".src").forEach((s) => {
  const pick = () => setMode(s.dataset.mode);
  s.addEventListener("click", pick);
  s.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
  });
});

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function provenance(f) {
  // the few facts that decide precedence, said plainly under the filename
  const bits = [];
  if (f.authority === "authoritative") bits.push("authoritative");
  if (f.starred) bits.push("starred");
  if (f.author) bits.push(f.author.split("@")[0]);
  if (f.modified) bits.push(f.modified);
  if (f.genre === "ai-notes") bits.push("machine transcript");
  if (f.audience && f.audience !== "unknown") bits.push(f.audience);
  return bits.length ? `<span class="prov">${esc(bits.join("  \u00b7  "))}</span>` : "";
}

function rowHtml(f, checked) {
  return `<label class="row${f.authority === "authoritative" ? " auth" : ""}">
    <input type="checkbox" value="${esc(f.path)}" ${checked ? "checked" : ""}>
    <span style="flex:1"><span class="nm">${esc(f.name || f.path.split("\\").pop())}</span>
    <span class="pth">${esc(f.path)}</span>
    ${provenance(f)}
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
  // a short suggestion list is usually the sensitivity gate doing its job, and
  // saying so here stops it reading as a folder that failed to scan properly
  const held = BLOCKED || [];
  $("#heldBack").innerHTML = held.length
    ? `<details style="margin:0 0 .6rem">
         <summary style="cursor:pointer;color:var(--soft);font-size:.82rem">
           ${held.length} more held back as personal or hiring material</summary>
         <ul style="margin:.5rem 0 0;padding-left:1.1rem;font-size:.78rem;color:var(--soft)">
         ${held.slice(0, 20).map((b) =>
           `<li>${esc((b.path || "").split("\\").pop())} <em>${esc((b.reason || "").replace(/^blocked: /, ""))}</em></li>`).join("")}
         ${held.length > 20 ? `<li>and ${held.length - 20} more</li>` : ""}
         </ul></details>`
    : "";
}

function renderVault() {
  $("#vaultList").innerHTML = MANIFEST.documents.map((d) =>
    rowHtml({ path: d.path, name: d.path.split("\\").pop(), reason: d.added_by,
              author: d.author, modified: d.modified, starred: d.starred,
              genre: d.genre, audience: d.audience, authority: d.authority })).join("") ||
    '<div class="row muted">empty</div>';
  $("#vaultCount").textContent = `${MANIFEST.documents.length} documents`;
}

$("#filter").addEventListener("input", renderSuggestions);

// ---- connect
async function refreshState() {
  const s = await api("/api/state");
  $("#vaultPath").textContent = s.vault;
  MANIFEST = s.manifest;
  REMOTES = s.remotes || [];
  REMOTES = s.remotes || [];
  renderVault();
}

async function doConnect(btnId, msgId, inputId, thenLoadDrives) {
  // blank means "make me a new one": the person signing in should not have to
  // invent a name for the connection
  const remote = $(inputId).value.trim();
  $(msgId).textContent = "a browser window will open, approve access there…";
  $(btnId).disabled = true;
  try {
    const r = await api("/api/connect", { remote });
    ACCOUNT = { connected: true, remote: r.remote, email: r.email };
    renderAccount();
    $(msgId).textContent = thenLoadDrives ? "connected, fetching your drives…" : "connected";
    await refreshState();
    if (thenLoadDrives) {
      await loadDrives(r.remote);
      $(msgId).textContent = r.email ? "connected as " + r.email : "connected";
    }
  } catch (e) {
    $(msgId).textContent = "failed: " + e.message;
  } finally {
    $(btnId).disabled = false;
  }
}
$("#btnConnect").addEventListener("click", () =>
  doConnect("#btnConnect", "#connectMsg", "#remoteName", true));
$("#btnConnect2").addEventListener("click", () =>
  doConnect("#btnConnect2", "#folderMsg", "#remoteName", false));

// ---- validate a folder before committing to reading it
$("#btnCheckFolder").addEventListener("click", async () => {
  $("#folderMsg").textContent = "checking…";
  try {
    const r = await api("/api/check_source",
      { mode: "folder", folder_url: $("#folderUrl").value, remote: currentRemote() });
    $("#folderMsg").textContent =
      `found "${r.label}"` + (r.shared_drive ? " (in a shared drive)" : "") + " — ready to read";
    SOURCE_OK = true;
    $("#btnScan").disabled = false;
  } catch (e) {
    SOURCE_OK = false;
    $("#btnScan").disabled = true;
    $("#folderMsg").textContent = e.message;
  }
});

$("#btnCheckLocal").addEventListener("click", async () => {
  $("#localMsg").textContent = "looking…";
  try {
    const r = await api("/api/check_source", { mode: "local", path: $("#localPath").value });
    $("#localMsg").textContent = `${r.count} documents, ${r.mb} MB — ready to read`;
    SOURCE_OK = true;
    $("#btnScan").disabled = false;
  } catch (e) {
    SOURCE_OK = false;
    $("#btnScan").disabled = true;
    $("#localMsg").textContent = e.message;
  }
});

async function loadDrives(remote) {
  // the first call after a token expires waits on an OAuth refresh and can take
  // the best part of a minute, so say so rather than leaving 'connect first' up
  $("#drives").textContent =
    "looking up your drives… the first time can take up to a minute";
  try {
    const d = await api("/api/drives", { remote });
    $("#drives").innerHTML = d.drives.map((x, i) =>
      `<label class="chk"><input type="checkbox" class="scope" data-id="${x.id || ""}"
        data-name="${esc(x.name)}" ${i === 0 ? "checked" : ""}> ${esc(x.name)}</label>`).join("");
    if (MODE === "drive") $("#btnScan").disabled = false;
    SOURCE_OK = true;
  } catch (e) { $("#drives").textContent = "could not list drives: " + e.message; }
}

$("#btnScan").addEventListener("click", async () => {
  // always say which Google account: the server default is a placeholder that
  // usually does not exist on the machine
  const body = { mode: MODE, remote: currentRemote() };
  if (MODE === "drive") {
    body.scopes = [...document.querySelectorAll(".scope:checked")].map((c) =>
      ({ id: c.dataset.id || null, name: c.dataset.name }));
    if (!body.scopes.length) return ($("#scanMsg").textContent = "pick at least one drive");
    $("#scanMsg").textContent = "scanning Drive, this can take a minute…";
  } else if (MODE === "folder") {
    body.folder_url = $("#folderUrl").value;
    $("#scanMsg").textContent = "reading that folder…";
  } else {
    body.path = $("#localPath").value;
    $("#scanMsg").textContent = "reading that folder…";
  }
  $("#btnScan").disabled = true;
  try {
    const r = await api("/api/scan", body);
    SUGGESTIONS = r.suggestions; BLOCKED = r.blocked;
    if (r.authors) { AUTHORS = r.authors; renderAuthorPicker(); }
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
async function setAuthority(level) {
  const paths = [...document.querySelectorAll("#vaultList input:checked")].map((c) => c.value);
  if (!paths.length) return;
  await api("/api/authority", { paths, level });
  await refreshState();
  renderVault();
}
$("#btnAuth").addEventListener("click", () => setAuthority("authoritative"));
$("#btnUnauth").addEventListener("click", () => setAuthority("normal"));

// ---- priority authors, picked from the people who actually own the documents
let AUTHORS = [];   // [{email, name, count}] discovered by the last scan
let CHOSEN = [];    // addresses currently carrying extra weight

function renderAuthorPicker() {
  const sel = $("#authorPick");
  const free = AUTHORS.filter((a) => !CHOSEN.includes(a.email));
  sel.innerHTML = free.length
    ? free.map((a) =>
        `<option value="${esc(a.email)}">${esc(a.name)} \u2014 ${esc(a.email)}` +
        `${a.count ? ` (${a.count} document${a.count > 1 ? "s" : ""})` : ""}</option>`).join("")
    : `<option value="">${AUTHORS.length
        ? "everyone already added" : "scan first to see who owns what"}</option>`;
  sel.disabled = !free.length;
  $("#btnAddAuthor").disabled = !free.length;

  $("#authorChips").innerHTML = CHOSEN.length
    ? CHOSEN.map((e) => {
        const a = AUTHORS.find((x) => x.email === e) || { name: e, email: e };
        return `<span class="chip">${esc(a.name)} <small>${esc(a.email)}</small>` +
               `<button type="button" data-drop="${esc(e)}" title="remove">&times;</button></span>`;
      }).join("")
    : `<span class="muted">No one carries extra weight. Documents rank on their own merits.</span>`;
  $("#authorChips").querySelectorAll("[data-drop]").forEach((b) =>
    b.addEventListener("click", () => {
      CHOSEN = CHOSEN.filter((x) => x !== b.dataset.drop);
      renderAuthorPicker();
    }));
}

async function loadAuthors() {
  try {
    const r = await api("/api/authors", {});
    AUTHORS = r.authors || [];
    CHOSEN = (r.selected || []).map((s) => s.toLowerCase());
    renderAuthorPicker();
  } catch (e) { /* the picker is a convenience; never block the screen on it */ }
}

$("#btnAddAuthor").addEventListener("click", () => {
  const v = $("#authorPick").value;
  if (v && !CHOSEN.includes(v)) { CHOSEN.push(v); renderAuthorPicker(); }
});

$("#btnSaveAuthors").addEventListener("click", async () => {
  $("#authorsMsg").textContent = "saving\u2026";
  try {
    const r = await api("/api/settings", { priority_authors: CHOSEN });
    if (r.suggestions) { SUGGESTIONS = r.suggestions; BLOCKED = r.blocked; renderSuggestions(); }
    const n = r.priority_authors.length;
    $("#authorsMsg").textContent = n
      ? `${n} priority author${n > 1 ? "s" : ""} saved, suggestions re-ranked`
      : "no priority authors set";
  } catch (e) { $("#authorsMsg").textContent = e.message; }
});

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
  const money = (v) => `$${v < 100 ? v.toFixed(2) : Math.round(v).toLocaleString()}`;
  $("#estStat").innerHTML =
    `<div><span>${e.documents}</span><small>documents</small></div>
     <div><span>${e.text_mb} MB</span><small>text to read</small></div>
     <div><span>~${(e.est_tokens / 1e6).toFixed(1)}M</span><small>estimated tokens</small></div>
     <div><span>~${e.est_hours}h</span><small>estimated build</small></div>
     <div><span>${money(e.floor["Sonnet 5"])} to ${money(e.costs["Sonnet 5"])}</span>
       <small>Sonnet 5</small></div>
     <div><span>${money(e.floor["Opus 5"])} to ${money(e.costs["Opus 5"])}</span>
       <small>Opus 5</small></div>`;
  $("#estNote").innerHTML =
    `${e.mb} MB of files, of which about ${e.text_mb} MB is readable text` +
    (e.measured ? ` (${e.measured} measured exactly, the rest inferred from format)` : ``) +
    `. The low figure is reading every document once, which is arithmetic. The high ` +
    `figure adds agent overhead and the linking pass, and rests on a single ` +
    `un-reconciled run, so it is the shakier end. List prices checked ` +
    `${e.prices_checked}; the pipeline runs Sonnet by default and Opus is shown for ` +
    `comparison. Neither figure is a quote.`;
  const unver = r.unverifiable || [];
  $("#unverBox").innerHTML = unver.length
    ? `<div class="info"><b>Shared with everyone</b>
        <p>${unver.length} document${unver.length > 1 ? "s" : ""} came from a folder rather than Drive, so
        ${unver.length > 1 ? "they carry" : "it carries"} no sharing settings to match people against.
        Notes built from ${unver.length > 1 ? "them" : "it"} are included in everyone's copy.</p>
        <ul style="margin:.5rem 0 0;padding-left:1.1rem;font-size:.82rem">
        ${unver.slice(0, 8).map((x) => `<li>${esc(x.split("\\").pop())}</li>`).join("")}
        </ul></div>`
    : "";
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
    if (r.preview_note) { $("#previewOut").innerHTML = `<div class="muted">${esc(r.preview_note)}</div>`; return; }
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

refreshState().then(() => Promise.all([loadAuthors(), loadAccount()]));
