"""Pick tonight's ingestion batch: new/changed live docs first, then an archive slice.

Writes _ingest/tonight.txt (one drive-relative path per line) and prints a summary.
Archive slice size is ~10% of the ORIGINAL archive set per night, so the backlog
clears in about 10 nights and then idles.

Exit 3 means nothing to do, so the nightly job can skip spending anything.
"""

import json
import re
import sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
DRIVE = WIKI.parent / "drive"
DRIVES = ["00_Operations", "01_Interventions", "02_External Affairs"]
MAX_DOCS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
BIG = 300 * 1024

SENSITIVE = [
    "02 people and culture", "01 hiring", "comp benchmarking", "work test",
    "candidate interview notes", "candidate -", "performance review", "payroll",
    "offer letter",
    # add specific names locally; keep real names out of version control
    "prospect_research", "prospect research", "wealth screen",
]


def in_archive(rel: str) -> bool:
    segs = re.split(r"[\\/]", rel)
    return any(s.startswith("99 ") or s.startswith("99_") or s.lower().endswith("archive")
               or s.lower() in ("archive", "deprecated") for s in segs)


def sensitive(rel: str) -> bool:
    low = rel.lower()
    return any(s in low for s in SENSITIVE)


def represented():
    FM = re.compile(r"^---\n(.*?)\n---", re.S)
    seen = set()
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
                    seen.add(re.sub(r"^drive\\", "", v, flags=re.I).lower())
    return seen


def main():
    done = represented()
    pending = WIKI / "_ingest" / "pending.json"
    picks, kinds = [], {}

    if pending.exists():
        p = json.loads(pending.read_text(encoding="utf-8"))
        for x in p.get("new", []) + p.get("changed", []):
            rel = x["path"]
            if len(picks) < MAX_DOCS and rel not in picks:
                picks.append(rel)
                kinds[rel] = "live"

    # archive slice fills any remaining room
    if len(picks) < MAX_DOCS:
        archive_all, archive_todo = [], []
        for dn in DRIVES:
            root = DRIVE / dn
            if not root.is_dir():
                continue
            for f in root.rglob("*.md"):
                rel = str(f.relative_to(DRIVE))
                if not in_archive(rel) or sensitive(rel):
                    continue
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                if size < 2048 or size > BIG or rel.lower().endswith(".xlsx.md"):
                    continue
                archive_all.append(rel)
                if rel.lower() not in done:
                    archive_todo.append(rel)
        per_night = max(1, round(len(archive_all) * 0.10))
        room = MAX_DOCS - len(picks)
        for rel in sorted(archive_todo)[:min(per_night, room)]:
            picks.append(rel)
            kinds[rel] = "archive"
        print(f"archive: {len(archive_todo)} of {len(archive_all)} still to ingest "
              f"(~{per_night}/night target)")

    (WIKI / "_ingest" / "tonight.txt").write_text("\n".join(picks), encoding="utf-8")
    live = sum(1 for r in picks if kinds[r] == "live")
    arch = sum(1 for r in picks if kinds[r] == "archive")
    print(f"tonight: {len(picks)} docs ({live} live, {arch} archive), cap {MAX_DOCS}")
    for r in picks:
        print(f"   {kinds[r]:<8} {r}")
    sys.exit(0 if picks else 3)


if __name__ == "__main__":
    main()
