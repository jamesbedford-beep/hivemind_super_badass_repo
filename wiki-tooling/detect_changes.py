"""Detect source docs that are new or changed since the last ingestion.

Compares current SHA-256 of every in-scope source doc against ledger.json, and
writes _ingest/pending.json describing the work. Free and deterministic: no model
tokens. The nightly job reads this to decide whether to spend anything at all.

Scope rules mirror the approved ingestion scope:
  - the three shared drives only (not My Drive / Shared with me)
  - skip archives, People and Culture, oversized files, spreadsheet conversions
  - skip anything matching the sensitive-excludes list
"""

import hashlib
import json
import re
import sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
VAULT = WIKI.parent
DRIVE = VAULT / "drive"
DRIVES = ["00_Operations", "01_Interventions", "02_External Affairs"]
BIG = 300 * 1024

SENSITIVE = [
    "02 people and culture", "01 hiring", "comp benchmarking", "work test",
    "candidate interview notes", "candidate -", "performance review", "payroll",
    "offer letter",
    # add specific names locally; keep real names out of version control
    "prospect_research", "prospect research", "wealth screen",
]
SKIP_NAME = re.compile(r"deprecated|running agenda|\bagenda\b|scheduling", re.I)


def winlong(p: Path) -> Path:
    s = str(p)
    return Path("\\\\?\\" + s) if not s.startswith("\\\\?\\") else p


def in_archive(rel: str) -> bool:
    segs = re.split(r"[\\/]", rel)
    return any(s.startswith("99 ") or s.startswith("99_") or s.lower().endswith("archive")
               or s.lower() in ("archive", "deprecated") for s in segs)


def in_scope(rel: str, size: int) -> bool:
    low = rel.lower()
    if in_archive(rel):
        return False                      # archives handled by the trickle, not here
    if any(s in low for s in SENSITIVE):
        return False
    if low.endswith(".xlsx.md") or size > BIG or size < 2048:
        return False
    if SKIP_NAME.search(Path(rel).name):
        return False
    return True


def main():
    ledger_path = WIKI / "_ingest" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    known = {}
    for slug, rec in ledger.items():
        src = (rec.get("source") or "").replace("/", "\\")
        # Ledger sources are written in several shapes over the pipeline's life:
        # "../drive/X", "..\\drive\\X", "drive\\X" and plain "X". Normalize all of
        # them to the mirror-relative form, otherwise nothing ever matches and the
        # same documents re-queue every night forever.
        src = re.sub(r"^(\.\.\\)+", "", src)
        src = re.sub(r"^drive\\", "", src, flags=re.I).lower()
        if src:
            known[src] = rec.get("sha256", "")

    # sources already represented in the wiki, from note frontmatter
    FM = re.compile(r"^---\n(.*?)\n---", re.S)
    represented = set()
    for d in ["concepts", "entities", "sources"]:
        for p in (WIKI / d).glob("*.md"):
            m = FM.match(p.read_text(encoding="utf-8", errors="replace"))
            if not m:
                continue
            sm = re.search(r"source:\s*\n((?:\s*-\s*.+\n?)+)", m.group(1))
            if not sm:
                continue
            for line in sm.group(1).splitlines():
                if "-" in line:
                    v = line.split("-", 1)[1].strip().strip('<>"\'').replace("/", "\\")
                    v = re.sub(r"^(\.\.\\)+", "", v)
                    represented.add(re.sub(r"^drive\\", "", v, flags=re.I).lower())

    # Content hashes of everything already ingested. Needed because the corpus
    # holds many differently-named copies of the same document (vShared/vInternal
    # exports, "Copy of ...", PDF twins). Without this the same content is
    # re-queued every night, and every night the ingestion agent correctly
    # rejects it as a duplicate: wasted tokens and a backlog that never clears.
    ingested_hashes = set()
    for rel_low in represented:
        p = DRIVE / rel_low
        if winlong(p).exists():
            try:
                ingested_hashes.add(hashlib.sha256(winlong(p).read_bytes()).hexdigest())
            except OSError:
                pass

    new, changed, dup_skipped = [], [], 0
    for dn in DRIVES:
        root = DRIVE / dn
        if not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(DRIVE))
            size = winlong(p).stat().st_size
            if not in_scope(rel, size):
                continue
            low = rel.lower()
            if low in represented or low in known:
                continue                   # already ingested; hash-change detection below
            try:
                h = hashlib.sha256(winlong(p).read_bytes()).hexdigest()
            except OSError:
                continue
            if h in ingested_hashes:
                dup_skipped += 1           # same content already in the wiki
                continue
            new.append({"path": rel, "size": size, "sha256": h})

    # changed detection for docs we have ingested
    for rel_low, old_hash in known.items():
        p = DRIVE / rel_low
        if not winlong(p).exists() or not old_hash:
            continue
        h = hashlib.sha256(winlong(p).read_bytes()).hexdigest()
        if h != old_hash:
            changed.append({"path": rel_low, "old": old_hash[:10], "new": h[:10]})

    out = {"new": new, "changed": changed,
           "counts": {"new": len(new), "changed": len(changed)}}
    (WIKI / "_ingest" / "pending.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"new in-scope docs not yet ingested: {len(new)}")
    print(f"skipped as duplicate content of an already-ingested doc: {dup_skipped}")
    print(f"previously ingested docs whose content changed: {len(changed)}")
    for x in new[:15]:
        print(f"   NEW      {x['path']}")
    for x in changed[:15]:
        print(f"   CHANGED  {x['path']}")
    # exit code signals whether there is work, for the scheduled job
    sys.exit(0 if (new or changed) else 3)


if __name__ == "__main__":
    main()
