"""Drive access for Team Vault, built on the rclone remote the pipeline already uses.

Deliberately does NOT ship its own OAuth client. rclone already handles the
browser consent flow, stores the token, and refreshes it. We drive rclone for
consent and listing, and reuse its access token for the permissions API.

Windows note: never let a Microsoft Store Python spawn rclone and rely on config
discovery. Store Python virtualises %APPDATA%, so the child reads a redirected
copy of rclone.conf with the wrong remotes in it. Always pass --config.
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/drive/v3"


def rclone_path():
    from shutil import which
    p = which("rclone")
    if p:
        return p
    base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for c in base.glob("Rclone.Rclone*/**/rclone.exe"):
        return str(c)
    raise RuntimeError("rclone not found. Install it with: winget install Rclone.Rclone")


def config_path():
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "rclone" / "rclone.conf"


def _run(args, timeout=180):
    cmd = [rclone_path(), "--config", str(config_path())] + args
    # utf-8 explicitly: rclone emits UTF-8, but Windows would otherwise decode
    # with the system codepage and blow up on unicode filenames.
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _json(args, timeout=180):
    code, out, err = _run(args, timeout)
    m = re.search(r"[\{\[].*[\}\]]", out, re.S)   # tolerate NOTICE lines
    if not m:
        raise RuntimeError(f"rclone returned no JSON: {(err or out)[:300]}")
    return json.loads(m.group(0))


def list_remotes():
    code, out, _ = _run(["listremotes"])
    return [l.strip().rstrip(":") for l in out.splitlines() if l.strip().endswith(":")]


def connect(remote):
    """Trigger rclone's browser consent flow. Blocks until the user finishes."""
    code, out, err = _run(["config", "create", remote, "drive", "scope=drive.readonly"], timeout=600)
    if code != 0:
        raise RuntimeError((err or out)[:400])
    return remote in list_remotes()


def access_token(remote):
    _run(["lsd", f"{remote}:", "--max-depth", "1"], timeout=120)   # forces refresh
    dump = _json(["config", "dump"])
    if remote not in dump:
        raise RuntimeError(f"remote '{remote}' not in {config_path()}. Found: {list(dump)}")
    return json.loads(dump[remote]["token"])["access_token"]


def api_get(token, path, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def shared_drives(token):
    return [{"id": d["id"], "name": d["name"]}
            for d in api_get(token, "drives", pageSize=100).get("drives", [])]


def list_files(remote, drive_id=None, drive_name=""):
    """Every file in a drive: path, size, and Drive id.

    Uses the same export formats as the sync, so Google Docs appear as .md and
    the listing lines up with what the mirror will contain.
    """
    target = f"{remote},team_drive={drive_id}:" if drive_id else f"{remote}:"
    files = _json(["lsjson", target, "-R", "--files-only", "--no-modtime",
                   "--no-mimetype", "--drive-export-formats", "md,xlsx,pptx"], timeout=900)
    out = []
    for f in files:
        fid = f.get("ID") or ""
        if isinstance(fid, list):
            fid = fid[0] if fid else ""
        fid = str(fid).split()[0] if str(fid).strip() else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", fid):
            continue
        rel = f["Path"].replace("/", "\\")
        out.append({"path": (drive_name + "\\" + rel if drive_name else rel),
                    "name": Path(rel).name,
                    "size": f.get("Size", 0) or 0,
                    "id": fid})
    return out


def can_access(token, file_id, email, domain=None):
    """Whether `email` can open this file. Covers inherited and direct grants."""
    try:
        p = api_get(token, f"files/{file_id}/permissions", supportsAllDrives="true",
                    pageSize="100", fields="permissions(type,role,emailAddress,domain)")
    except urllib.error.HTTPError:
        return None                      # unknown: caller should exclude
    email = (email or "").lower()
    for x in p.get("permissions", []):
        if x.get("emailAddress", "").lower() == email:
            return True
        if x.get("type") == "anyone":
            return True
        if domain and x.get("domain", "").lower() == domain:
            return True
    return False
