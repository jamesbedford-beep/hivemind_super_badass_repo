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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
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


def _token_expired(tok, margin=120):
    """True if the stored token is at, or nearly at, expiry."""
    raw = tok.get("expiry")
    if not raw:
        return True
    # rclone writes 7-digit fractional seconds; fromisoformat wants at most 6
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)
    try:
        exp = datetime.fromisoformat(raw)
    except ValueError:
        return True
    now = datetime.now(exp.tzinfo) if exp.tzinfo else datetime.now()
    return (exp - now).total_seconds() < margin


def access_token(remote):
    """Current access token for a remote, refreshing only when it has expired.

    Reads the config first, so a live token costs no subprocess at all. When the
    token has expired, one cheap API call makes rclone refresh it. rclone
    rewrites rclone.conf *after* that call returns, so the re-read is retried
    rather than assumed to be immediately consistent: reading the config while
    that write is in flight is what produced the intermittent KeyError.
    """
    detail = "no token stored"
    for attempt in range(3):
        dump = _json(["config", "dump"])
        if remote not in dump:
            raise RuntimeError(
                f"remote '{remote}' not in {config_path()}. Found: {list(dump)}")
        raw = dump[remote].get("token")
        if raw:
            try:
                tok = json.loads(raw)
                if tok.get("access_token") and not _token_expired(tok):
                    return tok["access_token"]
                detail = "token present but expired"
            except ValueError:
                detail = "token could not be parsed"
        if attempt < 2:
            _run(["about", f"{remote}:"], timeout=120)   # forces a refresh
            time.sleep(0.5)                              # let the config write land
    raise RuntimeError(
        f"could not get an access token for '{remote}' ({detail}). "
        f"Try:  rclone config reconnect {remote}:")


def _http_error(e):
    """Google's actual complaint, not just the status line."""
    try:
        err = json.loads(e.read().decode("utf-8", "replace"))["error"]
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        return reason, err.get("message", "")
    except Exception:
        return "", ""


def api_get(token, path, **params):
    """One Drive API call, retrying when Google throttles us.

    rclone ships a single shared OAuth client, so its per-minute quota is pooled
    across every rclone user in the world, not just this machine. Throttling is
    therefore routine and temporary rather than a sign anything is wrong, and it
    is worth waiting out rather than failing the whole scan.
    """
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    delay = 2.0
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            reason, message = _http_error(e)
            throttled = e.code == 429 or (
                e.code == 403 and reason in ("rateLimitExceeded", "userRateLimitExceeded"))
            if throttled and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            if throttled:
                raise RuntimeError(
                    "Google is rate limiting Drive requests. This is rclone's shared "
                    "OAuth client, whose quota is pooled across all rclone users, so it "
                    "is usually temporary. Wait a minute and try again, or create your "
                    "own client ID (see pipeline/README.md)."
                ) from None
            raise RuntimeError(
                f"Drive API {e.code}"
                + (f" ({reason})" if reason else "")
                + (f": {message}" if message else "")
            ) from None


def shared_drives(token):
    return [{"id": d["id"], "name": d["name"]}
            for d in api_get(token, "drives", pageSize=100).get("drives", [])]


def list_files(remote, drive_id=None, drive_name=""):
    """Every file in a drive: path, size, and Drive id.

    Uses the same export formats as the sync, so Google Docs appear as .md and
    the listing lines up with what the mirror will contain.
    """
    target = f"{remote},team_drive={drive_id}:" if drive_id else f"{remote}:"
    # --metadata rides along on the same request: mtime, owner and starred come
    # back for free, and they are what lets the linker reason about precedence
    files = _json(["lsjson", target, "-R", "--files-only", "--metadata",
                   "--drive-export-formats", "md,xlsx,pptx"], timeout=900)
    out = []
    for f in files:
        fid = f.get("ID") or ""
        if isinstance(fid, list):
            fid = fid[0] if fid else ""
        fid = str(fid).split()[0] if str(fid).strip() else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", fid):
            continue
        rel = f["Path"].replace("/", "\\")
        name = Path(rel).name
        if not readable(name):
            continue
        rec = {"path": (drive_name + "\\" + rel if drive_name else rel),
               "name": name, "size": f.get("Size", 0) or 0, "id": fid,
               "audience": audience_of(rel), "version": version_of(name),
               "genre": genre_of(name)}
        rec.update(_meta_fields(f))
        out.append(rec)
    return out


# Files that are never worth reading, whatever folder they turn up in.
LOCAL_SKIP_DIRS = {".git", ".svn", "node_modules", "__pycache__", ".obsidian",
                   ".venv", "venv", ".idea", ".vscode", "$RECYCLE.BIN"}
LOCAL_SKIP_EXTS = {".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".zip", ".tar",
                   ".gz", ".7z", ".rar", ".mp4", ".mov", ".avi", ".mkv", ".mp3",
                   ".wav", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
                   ".psd", ".ai", ".ttf", ".otf", ".woff", ".woff2", ".db", ".sqlite"}


# Version and audience markers that organisations put in filenames. Roughly one
# file in five carries a date, one in twelve a version marker, and one in
# fourteen an audience marker, so this is worth reading rather than discarding.
VERSION_RX = re.compile(r"(?:\b|_)v(\d+)(?:\b|_|\.)", re.I)
FINAL_RX = re.compile(r"(?:\b|_)(final|approved|signed|published)(?:\b|_|\.)", re.I)
DRAFT_RX = re.compile(r"(?:\b|_)(draft|wip|rough|scratch)(?:\b|_|\.)", re.I)
EXTERNAL_RX = re.compile(r"\b(external|public|shared|client|funder|donor[- ]facing|board)\b", re.I)
INTERNAL_RX = re.compile(r"\b(internal|internal[- ]only|team[- ]only|confidential)\b", re.I)
# AI note-takers, as opposed to notes a person wrote
AI_NOTES_RX = re.compile(
    r"transcript|otter(?:\.ai)?|fireflies|granola|read\.?ai|tl;?dv|"
    r"auto[-_ ]?notes|\brecording\b|gemini notes|copilot notes", re.I)


def audience_of(name):
    """internal / external / unknown, from how the file is named."""
    if INTERNAL_RX.search(name):
        return "internal"
    if EXTERNAL_RX.search(name):
        return "external"
    return "unknown"


def version_of(name):
    """A sortable rank for the same document at different stages.

    Higher wins. Explicit vN beats an unnumbered final, which beats an
    unmarked file, which beats anything calling itself a draft.
    """
    m = VERSION_RX.search(name)
    if m:
        try:
            return 100 + int(m.group(1))
        except ValueError:
            pass
    if FINAL_RX.search(name):
        return 50
    if DRAFT_RX.search(name):
        return -50
    return 0


def genre_of(name, content_type=""):
    """'ai-notes' for machine-written meeting records, else 'document'.

    Kept deliberately narrow: a human's meeting notes are primary material and
    must not be swept up with an auto-generated transcript.
    """
    return "ai-notes" if AI_NOTES_RX.search(name) else "document"


def readable(name):
    """False for files with no text in them.

    Applied to Drive listings as well as local folders: an image cannot be read,
    so offering one as a candidate document only wastes the reviewer's time.
    """
    return Path(name).suffix.lower() not in LOCAL_SKIP_EXTS


def _meta_fields(f):
    """The provenance rclone hands back, normalised."""
    md = f.get("Metadata") or {}
    owner = md.get("owner") or ""
    starred = str(md.get("starred", "")).lower() == "true"
    modified = md.get("mtime") or f.get("ModTime") or ""
    created = md.get("btime") or ""
    return {"modified": modified[:10], "created": created[:10],
            "author": owner, "starred": starred,
            "content_type": md.get("content-type", "")}


def display_name(email):
    """A readable name from an address, since Drive only gives us the address.

    ada.lovelace@example.org -> Ada Lovelace
    """
    local = (email or "").split("@")[0]
    local = re.sub(r"[._-]+", " ", local)
    local = re.sub(r"\d+", "", local).strip()
    if not local:
        return email or ""
    return " ".join(w[:1].upper() + w[1:] for w in local.split())


def owners_of(files):
    """Everyone who owns something in this scan, most documents first."""
    counts = {}
    for f in files:
        a = (f.get("author") or "").strip().lower()
        if a:
            counts[a] = counts.get(a, 0) + 1
    return [{"email": e, "name": display_name(e), "count": n}
            for e, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def folder_id_from_url(url):
    """The folder id out of whatever the user pasted.

    Accepts a full Drive URL, a sharing link with query junk on the end, or a
    bare id.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("Paste a Google Drive folder link.")
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", url):
        return url
    raise ValueError(
        "That does not look like a Google Drive folder link. It should look like "
        "https://drive.google.com/drive/folders/...")


def folder_meta(token, folder_id):
    """Name and owning shared drive of a folder, so it can be listed correctly."""
    meta = api_get(token, "files/" + folder_id,
                   fields="id,name,driveId,mimeType", supportsAllDrives="true")
    if meta.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError(
            f"'{meta.get('name', folder_id)}' is a file, not a folder. "
            "Paste the link to the folder that contains your documents.")
    return meta


def list_folder_files(remote, folder_id, token=None):
    """Every file under one Drive folder, and nothing outside it.

    A folder that lives in a shared drive has to be listed with that drive set
    as well, so the owning drive is looked up first when a token is available.
    """
    name, drive_id = "Folder", None
    if token:
        meta = folder_meta(token, folder_id)
        name = meta.get("name") or name
        drive_id = meta.get("driveId")
    parts = [remote, "root_folder_id=" + folder_id]
    if drive_id:
        parts.append("team_drive=" + drive_id)
    target = ",".join(parts) + ":"
    files = _json(["lsjson", target, "-R", "--files-only", "--metadata",
                   "--drive-export-formats", "md,xlsx,pptx"],
                  timeout=900)
    out = []
    for f in files:
        fid = f.get("ID") or ""
        if isinstance(fid, list):
            fid = fid[0] if fid else ""
        fid = str(fid).split()[0] if str(fid).strip() else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", fid):
            continue
        rel = f["Path"].replace("/", "\\")
        leaf = Path(rel).name
        if not readable(leaf):
            continue
        rec = {"path": name + "\\" + rel, "name": leaf,
               "size": f.get("Size", 0) or 0, "id": fid,
               "audience": audience_of(rel), "version": version_of(leaf),
               "genre": genre_of(leaf)}
        rec.update(_meta_fields(f))
        out.append(rec)
    return out


def list_local_files(root):
    """Every readable document in a folder on this machine. Touches no network.

    Files listed this way carry no Drive id, so they cannot be permission
    checked. Callers must treat them as unverifiable rather than as allowed.
    """
    base = Path(root).expanduser()
    if not base.exists():
        raise ValueError(f"No such folder: {base}")
    if not base.is_dir():
        raise ValueError(f"Not a folder: {base}")
    out = []
    for path in base.rglob("*"):
        try:
            rel = path.relative_to(base)
            if any(part in LOCAL_SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                continue
            if not path.is_file() or path.name.startswith((".", "~$")):
                continue
            if not readable(path.name):
                continue
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0:
            continue
        stat = path.stat()
        out.append({"path": base.name + "\\" + str(rel).replace("/", "\\"),
                    "name": path.name, "size": size, "id": "",
                    "local_path": str(path),
                    # a file on disk knows when it changed but not who wrote it
                    "modified": datetime.fromtimestamp(stat.st_mtime).date().isoformat(),
                    "created": "", "author": "", "starred": False,
                    "content_type": "",
                    "audience": audience_of(str(rel)),
                    "version": version_of(path.name),
                    "genre": genre_of(path.name)})
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
