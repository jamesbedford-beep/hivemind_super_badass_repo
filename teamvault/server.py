"""Team Vault: local web app for curating a team's shared context.

One command starts a local server, opens the browser, and walks a team lead
through Connect, Curate, Review, Build and Ship. Everything runs on this machine;
nothing is uploaded. Google consent is delegated to rclone, so no OAuth client
secret ships with this tool.

    python server.py [--vault PATH] [--port 8765]
"""

import argparse
import json
import mimetypes
import shutil
import subprocess
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import core
import manifest as M
import suggest

STATE = {
    "vault": None,
    "remote": "gdrive",
    "files": [],
    "sizes": {},
    "manifest": None,
    "build": {"running": False, "log": [], "done": False, "error": None},
}
HERE = Path(__file__).resolve().parent


def manifest_path():
    return Path(STATE["vault"]) / "team-manifest.json"


def load_or_new():
    p = manifest_path()
    if p.exists():
        return M.load(p)
    return M.new_manifest(team="", created_by="", scopes=[])


def api_state(_):
    m = STATE["manifest"] or load_or_new()
    STATE["manifest"] = m
    return {"vault": STATE["vault"], "remote": STATE["remote"],
            "remotes": core.list_remotes(), "manifest": m,
            "scanned": len(STATE["files"]), "build": STATE["build"]}


def api_connect(body):
    remote = body.get("remote") or STATE["remote"]
    core.connect(remote)
    STATE["remote"] = remote
    return {"ok": remote in core.list_remotes(), "remotes": core.list_remotes()}


def api_drives(body):
    STATE["remote"] = body.get("remote") or STATE["remote"]
    token = core.access_token(STATE["remote"])
    drives = core.shared_drives(token)
    return {"drives": drives + [{"id": None, "name": "My Drive"}]}


def api_scan(body):
    # accept the remote explicitly so a scan cannot silently use a stale default
    STATE["remote"] = body.get("remote") or STATE["remote"]
    scopes = body.get("scopes") or []
    files = []
    for s in scopes:
        files += core.list_files(STATE["remote"], s.get("id"), s.get("name", ""))
    STATE["files"] = files
    STATE["sizes"] = {f["path"]: f["size"] for f in files}
    m = STATE["manifest"] or load_or_new()
    m["scopes"] = [s.get("name") for s in scopes]
    STATE["manifest"] = m
    wiki = Path(STATE["vault"]) / "wiki"
    ranked, blocked = suggest.rank(files, wiki_dir=str(wiki) if wiki.is_dir() else None, limit=400)
    return {"total": len(files), "suggestions": ranked[:200], "blocked": blocked[:100]}


def api_add(body):
    m = STATE["manifest"]
    added = [p for p in body.get("paths", []) if M.add(m, p, body.get("reason", "manual"))]
    M.save(m, manifest_path())
    return {"added": len(added), "count": len(m["documents"]), "excluded": len(m["excluded"])}


def api_remove(body):
    m = STATE["manifest"]
    for p in body.get("paths", []):
        M.remove(m, p)
    M.save(m, manifest_path())
    return {"count": len(m["documents"])}


def api_review(body):
    m = STATE["manifest"]
    est = M.estimate(m, STATE["sizes"])
    preview = []
    emails = [e.strip() for e in body.get("emails", []) if e.strip()]
    if emails and STATE["files"]:
        token = core.access_token(STATE["remote"])
        idx = {f["path"]: f["id"] for f in STATE["files"]}
        sample = [d["path"] for d in m["documents"]][:60]
        for e in emails:
            dom = e.split("@")[-1].lower()
            yes = sum(1 for p in sample if idx.get(p) and core.can_access(token, idx[p], e, dom))
            pct = round(100 * yes / len(sample)) if sample else 0
            preview.append({"email": e, "sample": len(sample), "accessible": yes, "pct": pct})
    return {"estimate": est, "excluded": m["excluded"][:50], "access_preview": preview}


def _build_worker(vault):
    log = STATE["build"]["log"]
    try:
        script = HERE.parent / "pipeline" / "sync.ps1"
        log.append("step 1 of 3: mirroring the selected scopes from Drive")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", str(script), "-VaultPath", str(vault),
                            "-RemoteName", STATE["remote"]],
                           capture_output=True, text=True, timeout=7200)
        log.append("   sync exit=" + str(r.returncode))
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout)[-500:])
        log.append("step 2 of 3: distilling into notes (the expensive step)")
        log.append("   follow wiki-tooling/PIPELINE.md for the ingestion run")
        log.append("step 3 of 3: lint and index")
        lint = HERE.parent / "wiki-tooling" / "lint.py"
        if lint.exists():
            r2 = subprocess.run(["python", str(lint)], capture_output=True, text=True,
                                cwd=str(Path(vault) / "wiki"), timeout=600)
            log.append((r2.stdout or "")[-800:])
        STATE["build"]["done"] = True
    except Exception as e:
        STATE["build"]["error"] = str(e)
        log.append("ERROR: " + str(e))
    finally:
        STATE["build"]["running"] = False


def api_build(body):
    if STATE["build"]["running"]:
        return {"ok": False, "error": "a build is already running"}
    STATE["build"] = {"running": True, "log": [], "done": False, "error": None}
    M.save(STATE["manifest"], manifest_path())
    threading.Thread(target=_build_worker, args=(STATE["vault"],), daemon=True).start()
    return {"ok": True}


def api_build_status(_):
    return STATE["build"]


def api_ship(body):
    vault = Path(STATE["vault"])
    out = vault / "TeamVault-Setup"
    if out.exists():
        shutil.rmtree(out)
    (out / "wiki").mkdir(parents=True)
    for sub in ("concepts", "entities", "sources"):
        src = vault / "wiki" / sub
        if src.is_dir():
            shutil.copytree(src, out / "wiki" / sub, dirs_exist_ok=True)
    for f in ("index.md", "CLAUDE.md"):
        if (vault / "wiki" / f).exists():
            shutil.copy2(vault / "wiki" / f, out / "wiki" / f)
    M.save(STATE["manifest"], out / "team-manifest.json")
    for name in ("install.py", "core.py", "manifest.py"):
        if (HERE / name).exists():
            shutil.copy2(HERE / name, out / name)
    for name in ("setup.ps1", "sync.ps1", "convert.py", "dedupe.py", "excludes.txt"):
        src = HERE.parent / "pipeline" / name
        if src.exists():
            shutil.copy2(src, out / name)
    zip_path = shutil.make_archive(str(vault / "TeamVault-Setup"), "zip", str(out))
    notes = len(list((out / "wiki").rglob("*.md")))
    msg = ("Download TeamVault-Setup.zip, unzip it, and run:  python install.py\n"
           "It signs you into your own Google account and installs only the notes "
           "you already have access to.")
    return {"bundle": zip_path, "notes": notes, "message": msg}


ROUTES = {
    "/api/state": api_state, "/api/connect": api_connect, "/api/drives": api_drives,
    "/api/scan": api_scan, "/api/add": api_add, "/api/remove": api_remove,
    "/api/review": api_review, "/api/build": api_build,
    "/api/build/status": api_build_status, "/api/ship": api_ship,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ROUTES:
            try:
                return self._send(200, ROUTES[path]({}))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": str(e)})
        rel = "index.html" if path == "/" else path.lstrip("/")
        f = (HERE / "static" / rel).resolve()
        if f.is_file() and str(f).startswith(str((HERE / "static").resolve())):
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if path not in ROUTES:
            return self._send(404, {"error": "not found"})
        try:
            self._send(200, ROUTES[path](body))
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "Documents" / "TeamVault"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    Path(a.vault).mkdir(parents=True, exist_ok=True)
    STATE["vault"] = a.vault
    STATE["manifest"] = load_or_new()
    url = "http://127.0.0.1:" + str(a.port) + "/"
    print("Team Vault running at " + url)
    print("  vault: " + a.vault)
    print("  (ctrl+c to stop)")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
