"""Team Vault installer, run by each team member on their own machine.

Signs the person into their own Google account, works out which of the team
manifest's documents they can actually open, and installs only the notes derived
from those. Everything else is discarded before it is written to disk.

This is what makes a single shipped bundle safe: the access filter runs where the
credentials are, so nobody has to compute a per-person export by hand, and nobody
receives notes built from documents they cannot open.

    python install.py [--vault PATH] [--remote NAME]
"""

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import core
import manifest as M

HERE = Path(__file__).resolve().parent
FM = re.compile(r"^---\n(.*?)\n---", re.S)
LINK = re.compile(r"\[\[([^\]]+)\]\]")
CONV = re.compile(r"\.(docx|pptx|xlsx|pdf)\.md$", re.I)


def norm(name):
    n = CONV.sub("", name.lower())
    n = re.sub(r"\.md$", "", n)
    n = re.sub(r"^(copy of )+", "", n)
    return re.sub(r"[^a-z0-9]+", "", n.replace("：", ":").replace("／", "/"))


def note_sources(text):
    m = FM.match(text)
    if not m:
        return []
    sm = re.search(r"source:\s*\n((?:\s*-\s*.+\n?)+)", m.group(1))
    if not sm:
        return []
    out = []
    for line in sm.group(1).splitlines():
        if "-" in line:
            v = line.split("-", 1)[1].strip().strip('<>"\'')
            out.append(Path(v.replace("/", "\\")).name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(Path.home() / "Documents" / "TeamVault"))
    ap.add_argument("--remote", default="teamvault")
    ap.add_argument("--email", default=None, help="your Google address (detected if omitted)")
    a = ap.parse_args()

    bundle_wiki = HERE / "wiki"
    man_file = HERE / "team-manifest.json"
    if not bundle_wiki.is_dir() or not man_file.exists():
        sys.exit("Run this from inside the unzipped bundle (wiki/ and team-manifest.json expected).")
    man = M.load(man_file)
    print(f"Team Vault: {man.get('team') or 'team'} manifest, {len(man['documents'])} documents\n")

    # 1. Consent, read-only, in the person's own browser.
    if a.remote not in core.list_remotes():
        print("Opening your browser to sign in to Google (read-only access)...")
        core.connect(a.remote)
    token = core.access_token(a.remote)

    email = a.email
    if not email:
        try:
            about = core.api_get(token, "about", fields="user(emailAddress)")
            email = about["user"]["emailAddress"]
        except Exception:
            sys.exit("Could not detect your account. Re-run with --email you@example.org")
    domain = email.split("@")[-1].lower()
    print(f"signed in as {email}\n")

    # 2. Which manifest documents can this person actually open?
    print("checking your access to the team's documents...")
    drives = core.shared_drives(token)
    index = {}
    for d in drives + [{"id": None, "name": "My Drive"}]:
        try:
            for f in core.list_files(a.remote, d["id"], d["name"]):
                index[norm(f["name"])] = f["id"]
        except Exception:
            continue

    wanted = [Path(d["path"]).name for d in man["documents"]]
    ids = {w: index.get(norm(w)) for w in wanted}

    def check(w):
        fid = ids.get(w)
        if not fid:
            return w, None
        return w, core.can_access(token, fid, email, domain)

    allowed = set()
    unknown = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for w, ok in ex.map(check, wanted):
            if ok is True:
                allowed.add(norm(w))
            elif ok is None:
                unknown += 1
    print(f"  accessible: {len(allowed)} of {len(wanted)}")
    print(f"  not accessible or unresolved: {len(wanted) - len(allowed)} (excluded to be safe)\n")

    # 3. Keep only notes whose every source is accessible.
    vault = Path(a.vault)
    (vault / "wiki").mkdir(parents=True, exist_ok=True)
    kept, dropped = {}, 0
    for sub in ("concepts", "entities", "sources"):
        src = bundle_wiki / sub
        if not src.is_dir():
            continue
        for p in src.glob("*.md"):
            text = p.read_text(encoding="utf-8", errors="replace")
            srcs = note_sources(text)
            if srcs and all(norm(s) in allowed for s in srcs):
                kept[p.stem] = (sub, p, text)
            else:
                dropped += 1

    # 4. Scrub links pointing at notes this person is not getting.
    targets = set(kept)
    scrubbed = 0

    def fix(m):
        nonlocal scrubbed
        raw = m.group(1)
        tgt = raw.split("|")[0].split("#")[0].strip()
        if tgt in targets:
            return m.group(0)
        scrubbed += 1
        return raw.split("|")[-1].strip()

    for stem, (sub, p, text) in kept.items():
        out = vault / "wiki" / sub
        out.mkdir(parents=True, exist_ok=True)
        (out / p.name).write_text(LINK.sub(fix, text), encoding="utf-8")

    for extra in ("index.md", "CLAUDE.md"):
        s = bundle_wiki / extra
        if s.exists():
            (vault / "wiki" / extra).write_text(
                LINK.sub(fix, s.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")

    # 5. Install the tooling so their copy keeps itself current.
    (vault / "_pipeline").mkdir(exist_ok=True)
    for name in ("sync.ps1", "convert.py", "dedupe.py", "excludes.txt"):
        if (HERE / name).exists():
            shutil.copy2(HERE / name, vault / "_pipeline" / name)
    shutil.copy2(man_file, vault / "team-manifest.json")

    # 6. Verify nothing dangles.
    unresolved = set()
    for p in (vault / "wiki").rglob("*.md"):
        for m in LINK.finditer(p.read_text(encoding="utf-8", errors="replace")):
            t = m.group(1).split("|")[0].split("#")[0].strip()
            if t not in targets:
                unresolved.add(t)

    print(f"installed {len(kept)} notes to {vault / 'wiki'}")
    print(f"  withheld (outside your access): {dropped}")
    print(f"  links converted to plain text:  {scrubbed}")
    print(f"  unresolved links (must be 0):   {len(unresolved)}")
    print("\nNext:")
    print(f"  1. Open {vault} as an Obsidian vault, or point an AI assistant at it.")
    print(f"  2. To keep it current, set up your Drive mirror:")
    print(f"       powershell -ExecutionPolicy Bypass -File \"{vault / '_pipeline' / 'sync.ps1'}\""
          f" -VaultPath \"{vault}\" -RemoteName {a.remote}")


if __name__ == "__main__":
    main()
