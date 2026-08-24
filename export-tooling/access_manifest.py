"""Build the file manifest for a given teammate: which of THIS vault's source
documents they can access, and therefore which wiki notes an export would include.

Two modes, use either or both:

  A. Shared-drive membership (no API, instant, covers shared-drive corpora):
       --member-of "01_Interventions,02 External Affairs"
     You get these three answers from Drive > each shared drive > Manage members.

  B. Live permission check via the Google Drive API (uses the rclone remote's
     existing read-only token, so no new credentials):
       --email teammate@example.org --remote gdrive
     Checks shared-drive membership automatically, and per-file sharing for
     files outside shared drives (My Drive, Shared with me).

Output: a manifest of accessible source documents (feed straight to export.py
via --list), plus a coverage report of what it means for the wiki.

Usage:
  python access_manifest.py --vault "...\\MyVault" --email teammate@example.org --remote gdrive
  python access_manifest.py --vault "...\\MyVault" --member-of "01_Interventions"
"""

import argparse
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

FM = re.compile(r"^---\n(.*?)\n---", re.S)
DIRS = ["concepts", "entities", "sources"]
API = "https://www.googleapis.com/drive/v3"


def find_rclone():
    from shutil import which
    p = which("rclone")
    if p:
        return p
    base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for c in base.glob("Rclone.Rclone*/**/rclone.exe"):
        return str(c)
    sys.exit("rclone not found")


def default_config():
    """Real rclone.conf path.

    Microsoft Store Python virtualizes %APPDATA%, so a child rclone process can
    otherwise read a redirected copy of the config with different remotes in it.
    Build the path from the user profile and pass it explicitly.
    """
    return Path.home() / "AppData" / "Roaming" / "rclone" / "rclone.conf"


def rclone_json(rclone, args, config=None):
    pre = ["--config", str(config)] if config else []
    out = subprocess.run([rclone] + pre + args, capture_output=True, text=True).stdout
    m = re.search(r"[\{\[].*[\}\]]", out, re.S)   # tolerate NOTICE lines
    return json.loads(m.group(0)) if m else None


def get_token(rclone, remote, config=None):
    """Read the remote's access token, forcing a refresh if it looks stale."""
    for attempt in (0, 1):
        dump = rclone_json(rclone, ["config", "dump"], config) or {}
        if remote not in dump:
            sys.exit(f"remote '{remote}' not in rclone config (found: {list(dump)}). "
                     f"Pass --remote with the right name.")
        tok = json.loads(dump[remote]["token"])
        if attempt == 0:
            # cheap call makes rclone refresh and persist a new token if needed
            pre = ["--config", str(config)] if config else []
            subprocess.run([rclone] + pre + ["lsd", f"{remote}:", "--max-depth", "1"],
                           capture_output=True, text=True)
            continue
        return tok["access_token"]


def api_get(token, path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{API}/{path}?{q}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_id_index(path: Path):
    """Normalized mirror path -> Drive file id.

    Input is produced by access_manifest.ps1 as {driveName: [{Path, ID}, ...]}.
    It must be built in PowerShell: rclone launched from Microsoft Store Python
    reads a redirected copy of rclone.conf (the app container intercepts even an
    explicit --config path), so it cannot see the right remotes.
    """
    # utf-8-sig: PowerShell's Set-Content writes a BOM
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    idx = {}
    ID_OK = re.compile(r"^[A-Za-z0-9_-]{10,}$")
    for drive_name, files in raw.items():
        for f in files or []:
            p = f.get("Path") or ""
            fid = f.get("ID") or ""
            if isinstance(fid, list):        # duplicate Drive names can yield a list
                fid = fid[0] if fid else ""
            fid = str(fid).split()[0] if str(fid).strip() else ""   # drop tab-joined extras
            if p and ID_OK.match(fid):
                idx[norm_path(f"{drive_name}\\{p}")] = fid
    return idx


def norm_path(p: str) -> str:
    """Normalize a mirror or Drive path for matching."""
    p = p.replace("/", "\\")
    p = p.replace("ï¼š", ":").replace("ï¼", "/").replace("ï½œ", "|")
    p = re.sub(r"\.(docx|pptx|xlsx|pdf)\.md$", r".\1", p, flags=re.I)
    p = re.sub(r"\.md$", "", p, flags=re.I)
    return p.lower().strip()


def file_access(token, fid, email, domain, max_attempts=6):
    """Effective access for email on one file, using inherited + direct permissions.

    Retries with backoff on rate-limit responses. This matters: rclone's default
    client_id is shared across every rclone user globally, so its quota gets hit
    by traffic that has nothing to do with this run, and 429/403-rate-limit
    responses are common under concurrent per-file checks. Treating those as a
    real "no access" answer (the original bug here) silently corrupts results --
    verified counts swung wildly (e.g. 119 -> 21 for the same person, same files,
    consecutive runs) purely from retry-less rate-limit hits, not real changes in
    access. Only a real 4xx/5xx that persists after retries should ever count as
    resolved-false; anything else should surface as genuinely unresolved.
    """
    delay = 1.0
    last_err = None
    for attempt in range(max_attempts):
        try:
            p = api_get(token, f"files/{fid}/permissions", supportsAllDrives="true", pageSize="100",
                        fields="permissions(type,role,emailAddress,domain)")
            break
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            rate_limited = e.code == 429 or (e.code == 403 and "ateLimitExceeded" in body)
            last_err = f"HTTP {e.code}"
            if rate_limited and attempt < max_attempts - 1:
                time.sleep(delay + random.uniform(0, delay))
                delay = min(delay * 2, 20)
                continue
            return None, last_err
    else:
        return None, f"{last_err} (retries exhausted)"
    for x in p.get("permissions", []):
        if (x.get("emailAddress", "").lower() == email
                or (x.get("domain", "").lower() and x.get("domain", "").lower() == domain)
                or x.get("type") == "anyone"):
            return True, x.get("role", "")
    return False, ""


def wiki_sources(vault: Path):
    """Every source doc referenced by wiki notes -> the notes that cite it."""
    by_source = defaultdict(list)
    for d in DIRS:
        for p in (vault / "wiki" / d).glob("*.md"):
            m = FM.match(p.read_text(encoding="utf-8", errors="replace"))
            if not m:
                continue
            sm = re.search(r"source:\s*\n((?:\s*-\s*.+\n?)+)", m.group(1))
            if not sm:
                continue
            for line in sm.group(1).splitlines():
                if "-" not in line:
                    continue
                v = line.split("-", 1)[1].strip().strip('<>"\'').replace("/", "\\")
                v = re.sub(r"^(\.\.\\)+", "", v)
                v = re.sub(r"^drive\\", "", v, flags=re.I)
                if v:
                    by_source[v].append(p.stem)
    return by_source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--email", help="teammate's email, for the live API check")
    ap.add_argument("--remote", default="gdrive", help="rclone remote name for this vault's account")
    ap.add_argument("--member-of", default="", help="comma-separated shared drives they belong to (no API needed)")
    ap.add_argument("--out", default="manifest.txt")
    ap.add_argument("--max-file-checks", type=int, default=400,
                    help="cap on per-file API calls for non-shared-drive sources")
    ap.add_argument("--rclone-config", default=None,
                    help="path to rclone.conf (defaults to the real %%APPDATA%% location)")
    ap.add_argument("--verify-files", action="store_true", default=True,
                    help="verify each source doc's permissions individually (default on)")
    ap.add_argument("--no-verify-files", dest="verify_files", action="store_false",
                    help="trust shared-drive membership only (faster, can over-grant)")
    ap.add_argument("--id-index", default=None,
                    help="JSON {driveName: [{Path,ID}]} built by access_manifest.ps1; "
                         "required for per-file verification")
    ap.add_argument("--token", default=None,
                    help="OAuth access token. Use this (via access_manifest.ps1) when running "
                         "under Microsoft Store Python, whose %%APPDATA%% virtualization makes a "
                         "child rclone read a redirected copy of rclone.conf")
    a = ap.parse_args()
    cfg = Path(a.rclone_config) if a.rclone_config else default_config()

    vault = Path(a.vault)
    by_source = wiki_sources(vault)
    tops = defaultdict(list)
    for s in by_source:
        tops[s.split("\\")[0]].append(s)

    print(f"vault: {vault}")
    print(f"source docs behind the wiki: {len(by_source)}")
    for t, v in sorted(tops.items(), key=lambda kv: -len(kv[1])):
        print(f"   {len(v):>5}  {t}")

    granted_tops = {d.strip() for d in a.member_of.split(",") if d.strip()}
    accessible, undetermined = set(), []
    group_notes = set()

    if a.email:
        token = a.token or get_token(find_rclone(), a.remote, cfg)
        drives = api_get(token, "drives", pageSize=100).get("drives", [])
        print(f"\nshared drives visible to this account: {len(drives)}")
        for d in drives:
            try:
                perms = api_get(token, f"files/{d['id']}/permissions",
                                supportsAllDrives="true", pageSize="100",
                                fields="permissions(type,role,emailAddress,domain)")
                entries = perms.get("permissions", [])
                emails = {p.get("emailAddress", "").lower() for p in entries}
                domains = {p.get("domain", "").lower() for p in entries}
                # group grants cannot be expanded without Admin SDK access
                groups = {p.get("emailAddress", "").lower() for p in entries
                          if p.get("type") == "group" and p.get("emailAddress")}
                group_notes.update(groups)
                dom = a.email.split("@")[-1].lower()
                is_member = a.email.lower() in emails or dom in domains
                print(f"   {'MEMBER ' if is_member else 'no     '} {d['name']}")
                if is_member:
                    granted_tops.add(d["name"])
            except urllib.error.HTTPError as e:
                print(f"   ?       {d['name']} (permission check failed: HTTP {e.code})")
                undetermined.append(d["name"])

    for t in granted_tops:
        accessible.update(tops.get(t, []))

    # Personal-drive sources (My Drive, Shared with me) have no membership concept
    # to check -- access is per file, always, regardless of --member-of. Queue
    # them for the same per-file verification as shared-drive files: My Drive
    # entries are owned by this account (so file_access() resolves them
    # definitively); Shared with me entries are owned by others and will come
    # back unresolved (HTTPError) rather than be wrongly granted -- that is
    # correct, not a bug (see README's Shared-with-me limitation).
    personal_tops = {t for t in tops if t in ("My Drive", "Shared with me")}
    for t in personal_tops:
        accessible.update(tops.get(t, []))

    # Per-file verification. Drive membership is only a proxy: folders inside a
    # shared drive can carry their own permissions, and non-members can hold
    # access to individual folders. Verify every doc we are about to grant.
    denied_detail = []
    if a.email and a.verify_files and accessible and not a.id_index:
        print("\nWARNING: no --id-index supplied, so per-file verification is SKIPPED.")
        print("  Shared-drive membership alone can over-grant: folders inside a drive carry")
        print("  their own permissions. Run via access_manifest.ps1 to verify properly.")
    if a.email and a.verify_files and accessible and a.id_index:
        from concurrent.futures import ThreadPoolExecutor
        idx = load_id_index(Path(a.id_index))
        print(f"\nfile-id index entries: {len(idx)}")
        dom = a.email.split("@")[-1].lower()
        em = a.email.lower()
        targets = sorted(accessible)
        print(f"\nverifying {len(targets)} files individually (drive membership is only a proxy)...")

        def check(rel):
            fid = idx.get(norm_path(rel))
            if not fid:
                return rel, None, "no id match"
            ok, role = file_access(token, fid, em, dom)
            return rel, ok, role

        verified, unknown = set(), []
        with ThreadPoolExecutor(max_workers=4) as ex:
            for rel, ok, role in ex.map(check, targets):
                if ok is True:
                    verified.add(rel)
                elif ok is False:
                    denied_detail.append(rel)
                else:
                    unknown.append((rel, role))
        print(f"   verified accessible: {len(verified)}")
        print(f"   DENIED at file level: {len(denied_detail)}  <- would have leaked on membership alone")
        print(f"   could not resolve: {len(unknown)} (excluded to be safe)")

        def top_counts(rels):
            c = defaultdict(int)
            for r in rels:
                c[r.split("\\")[0]] += 1
            return dict(c)
        print(f"   breakdown by top folder -- accessible: {top_counts(verified)}")
        print(f"   breakdown by top folder -- denied:      {top_counts(denied_detail)}")
        print(f"   breakdown by top folder -- unresolved:   {top_counts(r for r, _ in unknown)}")
        for rel in denied_detail[:15]:
            print(f"      denied: {rel}")
        accessible = verified

    # anything not covered by a granted shared drive and not attempted above
    # (personal_tops are attempted via per-file verification, not left over)
    leftover = [s for s in by_source
                if s.split("\\")[0] not in granted_tops and s.split("\\")[0] not in personal_tops]
    personal = [s for s in leftover if s.split("\\")[0] in ("My Drive", "Shared with me")]

    manifest = sorted(accessible)
    Path(a.out).write_text("\n".join(Path(s).name for s in manifest), encoding="utf-8")

    notes = {n for s in manifest for n in by_source[s]}
    print(f"\nACCESSIBLE source docs: {len(manifest)} of {len(by_source)}")
    print(f"wiki notes citing at least one accessible doc: {len(notes)}")
    print(f"not covered: {len(leftover)} docs ({len(personal)} in My Drive / Shared with me)")
    if personal:
        print("  NOTE: My Drive and Shared with me are per-file access. Files you own can be")
        print("  checked in Drive; files owned by others cannot be audited by you. Safest is to")
        print("  exclude them, or confirm with the recipient directly.")
    if group_notes:
        print("\nGROUP GRANTS DETECTED (cannot be expanded by this API):")
        for g in sorted(group_notes):
            print(f"   {g}")
        print("  If this person belongs to one of these groups they may have MORE access than")
        print("  reported above. Check group membership in Google Admin, or ask them.")
    print(f"\nmanifest written to {a.out}  (feed to export.py --list)")


if __name__ == "__main__":
    main()
