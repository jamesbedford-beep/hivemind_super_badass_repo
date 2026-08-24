"""Rebuild concept-index.json from the notes on disk (source of truth).

Fixes two drift problems that accumulate across ingestion runs:
  - notes present on disk but missing from the index (future runs would then
    create duplicates instead of merging into them)
  - index entries pointing at files that no longer exist (merged away)

Preserves existing entries' sources lists where the note still exists, so
provenance recorded in the index is not lost.
"""

import json
import re
from pathlib import Path

WIKI = Path(r"C:\Users\you\Documents\MyVault\wiki")
DIRS = ["concepts", "entities", "sources"]
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def field(fm, name):
    m = re.search(rf"^{name}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip('"\'') if m else None


def listfield(fm, name):
    m = re.search(rf"{name}:\s*\[(.*?)\]", fm)
    if m:
        return [x.strip().strip('"\'') for x in m.group(1).split(",") if x.strip()]
    b = re.search(rf"{name}:\s*\n((?:\s*-\s*.+\n?)+)", fm)
    if b:
        return [l.split("-", 1)[1].strip().strip('<>"\'') for l in b.group(1).splitlines() if l.strip()]
    return []


ci_path = WIKI / "_ingest" / "concept-index.json"
old = {}
if ci_path.exists():
    try:
        old = json.loads(ci_path.read_text(encoding="utf-8"))
    except Exception:
        old = {}

new, added, kept = {}, 0, 0
for d in DIRS:
    for p in sorted((WIKI / d).glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        m = FM_RE.match(text)
        fm = m.group(1) if m else ""
        uid = field(fm, "uid") or re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-")
        title = field(fm, "title") or p.stem
        entry = {
            "path": f"{d}/{p.name}",
            "title": title,
            "aliases": listfield(fm, "aliases"),
            "tags": listfield(fm, "tags"),
            "sources": listfield(fm, "source"),
        }
        if uid in old:
            kept += 1
            # keep any richer sources recorded in the old index
            merged = list(dict.fromkeys(entry["sources"] + old[uid].get("sources", [])))
            entry["sources"] = merged
        else:
            added += 1
        new[uid] = entry

dead = [uid for uid, e in old.items() if uid not in new]
ci_path.write_text(json.dumps(new, indent=1, ensure_ascii=True), encoding="utf-8")
print(f"index rebuilt: {len(new)} entries")
print(f"  newly indexed (were missing): {added}")
print(f"  carried over: {kept}")
print(f"  dropped stale entries (file gone): {len(dead)}")
for uid in dead[:15]:
    print(f"    {uid} -> {old[uid].get('path')}")
