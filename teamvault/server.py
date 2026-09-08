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
    "mode": "drive",          # drive | folder | local
    "source_label": "",
    "account": {},            # {remote: email}, so we ask Google only once
    "files": [],
    "sizes": {},
    "manifest": None,
    "build": {"running": False, "log": [], "done": False, "error": None},
}
HERE = Path(__file__).resolve().parent


def resolve_remote(preferred=None):
    """The account to use, preferring what was asked for.

    The default is a placeholder name that often does not exist locally. Rather
    than failing on it, fall back to the configured account when there is only
    one, which is the usual case.
    """
    have = core.list_remotes()
    for candidate in (preferred, STATE.get("remote")):
        if candidate and candidate in have:
            return candidate
    if len(have) == 1:
        return have[0]
    if not have:
        raise RuntimeError(
            "No Google account is set up yet. Use Connect with Google first.")
    raise RuntimeError(
        f"Pick which account to use. Found: {', '.join(have)}")


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
            "mode": STATE["mode"], "source_label": STATE["source_label"],
            "scanned": len(STATE["files"]), "build": STATE["build"]}


def api_connect(body):
    # a fresh connection gets a name of our choosing: the person signing in has
    # no reason to invent one, and 'gdrive' collides with existing setups
    remote = (body.get("remote") or "").strip()
    if not remote:
        existing = set(core.list_remotes())
        remote = "hivemind"
        n = 2
        while remote in existing:
            remote = f"hivemind{n}"
            n += 1
    core.connect(remote)
    ok = remote in core.list_remotes()
    if ok:
        STATE["remote"] = remote
        STATE["account"].pop(remote, None)
    return {"ok": ok, "remote": remote, "email": signed_in_as(remote) if ok else "",
            "remotes": core.list_remotes()}


def api_drives(body):
    STATE["remote"] = resolve_remote(body.get("remote"))
    token = core.access_token(STATE["remote"])
    drives = core.shared_drives(token)
    return {"drives": drives + [{"id": None, "name": "My Drive"}]}


def collect_files(mode, body):
    """The candidate documents for the chosen source. Returns (files, label).

    'drive' walks whole drives, 'folder' stays inside one Drive folder, and
    'local' never contacts Google at all.
    """
    if mode == "local":
        path = (body.get("path") or "").strip()
        if not path:
            raise RuntimeError("Give the folder on this computer to read.")
        files = core.list_local_files(path)
        if not files:
            raise RuntimeError(f"No readable documents found in {path}")
        return files, str(Path(path).expanduser())

    if mode == "folder":
        fid = core.folder_id_from_url(body.get("folder_url"))
        token = core.access_token(STATE["remote"])
        meta = core.folder_meta(token, fid)
        files = core.list_folder_files(STATE["remote"], fid, token)
        if not files:
            raise RuntimeError(
                f"'{meta.get('name')}' has no documents in it, or none you can open.")
        return files, meta.get("name") or fid

    scopes = body.get("scopes") or []
    if not scopes:
        raise RuntimeError("Pick at least one drive to scan.")
    files, seen = [], set()
    for s in scopes:
        for f in core.list_files(STATE["remote"], s.get("id"), s.get("name", "")):
            # the same document can surface in more than one scope, most often
            # via 'Shared with me' alongside the shared drive it really lives in
            if f["path"] in seen:
                continue
            seen.add(f["path"])
            files.append(f)
    return files, ", ".join(s.get("name", "") for s in scopes)


def api_scan(body):
    # accept the remote explicitly so a scan cannot silently use a stale default
    mode = body.get("mode") or "drive"
    if mode != "local":
        STATE["remote"] = resolve_remote(body.get("remote"))
    if mode not in ("drive", "folder", "local"):
        raise RuntimeError(f"unknown source '{mode}'")
    files, label = collect_files(mode, body)
    STATE["mode"], STATE["source_label"] = mode, label
    STATE["files"] = files
    # accumulate rather than replace: a manifest can span more than one scan,
    # and a document whose size is forgotten silently shrinks the estimate
    STATE["sizes"].update({f["path"]: f["size"] for f in files})
    m = STATE["manifest"] or load_or_new()
    m["scopes"] = [label]
    m["source_mode"] = mode
    STATE["manifest"] = m
    wiki = Path(STATE["vault"]) / "wiki"
    ranked, blocked = suggest.rank(files, wiki_dir=str(wiki) if wiki.is_dir() else None,
                                   limit=400, priority_authors=m.get("priority_authors", []))
    return {"total": len(files), "suggestions": ranked[:200], "blocked": blocked[:100],
            "mode": mode, "label": label, "authors": core.owners_of(files)}


def api_add(body):
    m = STATE["manifest"]
    src = "local" if STATE["mode"] == "local" else "drive"
    meta_by_path = {f["path"]: f for f in STATE["files"]}
    added = [p for p in body.get("paths", [])
             if M.add(m, p, body.get("reason", "manual"), source=src,
                      meta=meta_by_path.get(p))]
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
    est = M.estimate(m, STATE["sizes"], vault=STATE["vault"])
    preview = []
    emails = [e.strip() for e in body.get("emails", []) if e.strip()]
    # only Drive-backed documents have permissions to sample; local ones would
    # otherwise drag every percentage down and imply a check that never ran
    checkable = [d["path"] for d in m["documents"] if d.get("source") != "local"]
    idx = {f["path"]: f["id"] for f in STATE["files"] if f.get("id")}
    sample = [p for p in checkable if idx.get(p)][:60]
    note = ""
    if emails and not checkable:
        note = "Nothing to check: every document came from a folder, not from Drive."
    elif emails and not sample:
        note = ("Nothing to check against yet. Scan the Drive these documents came "
                "from and the preview can look up their permissions.")
    elif emails:
        # a broken or unconfigured remote should cost the preview, not the
        # whole review screen
        try:
            token = core.access_token(STATE["remote"])
            for e in emails:
                dom = e.split("@")[-1].lower()
                yes = sum(1 for p in sample if core.can_access(token, idx[p], e, dom))
                preview.append({"email": e, "sample": len(sample), "accessible": yes,
                                "pct": round(100 * yes / len(sample))})
        except Exception as exc:
            note = "Could not check access: " + str(exc)
    return {"estimate": est, "excluded": m["excluded"][:50], "access_preview": preview,
            "preview_note": note,
            "unverifiable": [d["path"] for d in M.unverifiable(m)][:50],
            "mode": m.get("source_mode", "drive")}


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


RECIPIENT_README = """# Start here

You have been sent your team's shared knowledge base. Setting it up takes about
five minutes and installs only the notes you are already allowed to see.

## What you need

- Python 3.10 or newer
- rclone (`winget install Rclone.Rclone` on Windows)

## Install

From this folder, run:

    python install.py

It opens your browser so you can sign in to your own Google account. The access
is read-only: nothing here can change anything in Drive.

It then checks, document by document, which of the team's sources you can open,
and installs only the notes built entirely from those. Notes you are not
entitled to are discarded before anything is written to disk, and any link
pointing at one of them is turned into plain text so you never see a dead end.

## What you get

A `wiki` folder of short, cross-linked notes. Open it as an Obsidian vault, or
point an AI assistant at the folder and ask it questions.

## Keeping it current

`install.py` prints a `sync.ps1` command at the end. Run it to mirror Drive
yourself so your copy stays up to date. That step also needs markitdown
(`pip install markitdown[all]`) to read Office and PDF files.

## Notes

- Re-run `python install.py` any time. It refreshes what you can see and
  removes anything you no longer have access to.
- If it ends with an error about unresolved links, send the output to whoever
  built the bundle rather than using the vault.
"""


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
    (out / "START-HERE.md").write_text(RECIPIENT_README, encoding="utf-8")
    zip_path = shutil.make_archive(str(vault / "TeamVault-Setup"), "zip", str(out))
    notes = len(list((out / "wiki").rglob("*.md")))
    msg = ("Download TeamVault-Setup.zip, unzip it, and run:  python install.py\n"
           "It signs you into your own Google account and installs only the notes "
           "you already have access to.")
    return {"bundle": zip_path, "notes": notes, "message": msg}


def api_authority(body):
    """Mark documents authoritative, normal, or superseded."""
    m = STATE["manifest"]
    level = body.get("level", "normal")
    n = sum(1 for p in body.get("paths", []) if M.set_authority(m, p, level))
    M.save(m, manifest_path())
    return {"updated": n, "level": level}


def signed_in_as(remote):
    """The email behind a connection, cached: it never changes for a remote."""
    if remote in STATE["account"]:
        return STATE["account"][remote]
    try:
        token = core.access_token(remote)
        email = core.api_get(token, "about", fields="user(emailAddress)")
        email = email["user"]["emailAddress"]
    except Exception:
        email = ""
    STATE["account"][remote] = email
    return email


def api_whoami(_):
    """Which Google account the tool is using, in the words a person uses."""
    remotes = core.list_remotes()
    if not remotes:
        return {"connected": False, "accounts": []}
    try:
        current = resolve_remote()
    except RuntimeError:
        current = remotes[0]
    return {"connected": True, "remote": current, "email": signed_in_as(current),
            "accounts": [{"remote": r, "email": signed_in_as(r)} for r in remotes]}


def api_authors(_):
    """Document owners from the last scan, so the picker has real people in it."""
    m = STATE["manifest"] or load_or_new()
    known = core.owners_of(STATE["files"])
    # anyone already chosen stays selectable even if they own nothing in this scan
    have = {a["email"] for a in known}
    for e in m.get("priority_authors", []):
        if e.lower() not in have:
            known.append({"email": e.lower(), "name": core.display_name(e), "count": 0})
    return {"authors": known, "selected": m.get("priority_authors", [])}


def api_settings(body):
    """Read or update the manifest's own settings. Empty body just reads."""
    m = STATE["manifest"]
    if "priority_authors" in body:
        m["priority_authors"] = [a.strip() for a in body["priority_authors"] if a.strip()]
        M.save(m, manifest_path())
        # the ranking depends on this, so re-rank what is already on screen
        if STATE["files"]:
            wiki = Path(STATE["vault"]) / "wiki"
            ranked, blocked = suggest.rank(
                STATE["files"], wiki_dir=str(wiki) if wiki.is_dir() else None,
                limit=400, priority_authors=m["priority_authors"])
            return {"priority_authors": m["priority_authors"],
                    "suggestions": ranked[:200], "blocked": blocked[:100]}
    return {"priority_authors": m.get("priority_authors", [])}


def api_check_source(body):
    """Validate a source and say how much is there, without ranking anything."""
    mode = body.get("mode") or "drive"
    if mode == "local":
        path = (body.get("path") or "").strip()
        files = core.list_local_files(path)
        total = sum(f["size"] for f in files)
        return {"ok": True, "count": len(files), "mb": round(total / (1024 * 1024), 1),
                "label": str(Path(path).expanduser())}
    if mode == "folder":
        fid = core.folder_id_from_url(body.get("folder_url"))
        remote = resolve_remote(body.get("remote"))
        token = core.access_token(remote)
        meta = core.folder_meta(token, fid)
        # a check that succeeded is the best evidence of the right account, so
        # keep it rather than letting the scan fall back to the default
        STATE["remote"] = remote
        return {"ok": True, "label": meta.get("name"), "id": fid,
                "remote": remote, "shared_drive": bool(meta.get("driveId"))}
    return {"ok": True}


ROUTES = {
    "/api/check_source": api_check_source,
    "/api/authority": api_authority,
    "/api/authors": api_authors,
    "/api/whoami": api_whoami,
    "/api/settings": api_settings,
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
