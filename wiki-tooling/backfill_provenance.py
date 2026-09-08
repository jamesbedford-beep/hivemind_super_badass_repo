"""Stamp provenance onto notes that were written before it was captured.

Existing notes carry only the date they were ingested, which tells you nothing
about how old the underlying claim is. This reads each note's `source:` paths,
finds those files in the local mirror, and writes `source_modified` plus the
audience, genre and version markers that can be read from the filename.

Author is deliberately not backfilled: it is not recoverable from the mirror,
and a guessed author is worse than a missing one.

    python backfill_provenance.py --vault "C:\\Users\\you\\Documents\\MyVault"
    python backfill_provenance.py --vault ... --apply     # write the changes
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "teamvault"))
import core  # noqa: E402  the single source of truth for these classifications

FM = re.compile(r"^---\n(.*?)\n---", re.S)
SOURCES = re.compile(r"^source:\s*\n((?:\s*-\s*.+\n?)+)", re.M)


def winlong(p):
    s = str(p)
    return Path("\\\\?\\" + s) if not s.startswith("\\\\?\\") else p


def source_paths(front):
    m = SOURCES.search(front)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        if "-" in line:
            v = line.split("-", 1)[1].strip().strip("<>\"'")
            v = re.sub(r"^(\.\./)+", "", v.replace("\\", "/"))
            v = re.sub(r"^drive/", "", v, flags=re.I)
            out.append(v)
    return out


def resolve(drive_dir, rel):
    p = winlong(drive_dir / rel)
    if p.exists():
        return p
    # the mirror stores converted files as "<original>.md"
    for cand in (drive_dir / (rel + ".md"), drive_dir / re.sub(r"\.md$", "", rel)):
        if winlong(cand).exists():
            return winlong(cand)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    a = ap.parse_args()

    vault = Path(a.vault)
    wiki, drive_dir = vault / "wiki", vault / "drive"
    if not wiki.is_dir():
        sys.exit(f"No wiki folder at {wiki}")

    notes = [p for p in wiki.rglob("*.md") if p.name not in ("CLAUDE.md",)]
    stats = {"notes": len(notes), "updated": 0, "already": 0,
             "no_source": 0, "unresolved": 0}
    span = []

    for note in notes:
        text = winlong(note).read_text(encoding="utf-8", errors="replace")
        m = FM.match(text)
        if not m:
            continue
        front = m.group(1)
        if "source_modified:" in front:
            stats["already"] += 1
            continue
        rels = source_paths(front)
        if not rels:
            stats["no_source"] += 1
            continue

        dates, names = [], []
        for rel in rels:
            f = resolve(drive_dir, rel)
            if f:
                dates.append(date.fromtimestamp(f.stat().st_mtime).isoformat())
                names.append(Path(rel).name)
        if not dates:
            stats["unresolved"] += 1
            continue

        newest = max(dates)
        leaf = names[0]
        add = [f"source_modified: {newest}",
               f"audience: {core.audience_of(leaf)}",
               f"genre: {core.genre_of(leaf)}",
               "authority: normal"]
        v = core.version_of(leaf)
        if v:
            add.append(f"version_rank: {v}")

        # insert directly after the source block so provenance stays together
        # the source-block match swallows its trailing newline, so put one
        # back on each side or the next key runs into the last value
        sm = SOURCES.search(front)
        head = front[:sm.end()].rstrip("\n")
        tail = front[sm.end():].lstrip("\n")
        new_front = head + "\n" + "\n".join(add) + ("\n" + tail if tail else "")
        # refuse to write frontmatter whose top-level lines are not key: value
        bad = [l for l in new_front.splitlines()
               if l.strip() and not l.startswith((" ", "-", "\t")) and ":" not in l]
        if bad:
            print("  SKIPPED, would break frontmatter: %s %r" % (note.name, bad[:2]))
            stats["unresolved"] += 1
            continue
        if a.apply:
            winlong(note).write_text(text.replace(front, new_front, 1), encoding="utf-8")
        stats["updated"] += 1
        span.append(newest)

    print(("APPLIED" if a.apply else "DRY RUN") + f" over {stats['notes']} notes")
    print(f"  would stamp provenance : {stats['updated']}")
    print(f"  already had it         : {stats['already']}")
    print(f"  no source listed       : {stats['no_source']}")
    print(f"  sources not in mirror  : {stats['unresolved']}")
    if span:
        print(f"  source dates span      : {min(span)} to {max(span)}")
    if not a.apply and stats["updated"]:
        print("\nRe-run with --apply to write these.")


if __name__ == "__main__":
    main()
