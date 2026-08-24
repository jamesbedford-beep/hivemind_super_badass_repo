"""Phase 0 discovery + triage: enumerate .md sources, hash, assign tiers.

Tiers: ingest | summarize-only | skip. Heuristic first pass; the human-approved
list is what Phase 1 actually runs on. Writes triage-<scope>.json and a
human-readable triage-<scope>-report.md next to this script.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

SIZE_SKIP = 2 * 1024          # < 2 KB: scraps
SIZE_SUMMARIZE = 300 * 1024   # > 300 KB: transcripts / oversized

SKIP_NAME = re.compile(r"deprecated|running agenda|\bagenda\b|scheduling", re.I)
SUMMARIZE_NAME = re.compile(r"transcript|interview|syncs?\b|meeting notes", re.I)


def tier_for(path: Path, size: int) -> tuple[str, str]:
    name = path.name
    if size < SIZE_SKIP:
        return "skip", f"tiny ({size} B)"
    if SKIP_NAME.search(name):
        return "skip", "logistics/deprecated name"
    if name.lower().endswith(".xlsx.md"):
        return "skip", "spreadsheet conversion (tables, no prose)"
    if SUMMARIZE_NAME.search(name):
        return "summarize-only", "transcript/meeting-style name"
    if size > SIZE_SUMMARIZE:
        return "summarize-only", f"oversized ({size // 1024} KB)"
    return "ingest", ""


def winlong(p: Path) -> Path:
    """Extended-length path form so files beyond MAX_PATH (260 chars) work."""
    s = str(p)
    return Path("\\\\?\\" + s) if not s.startswith("\\\\?\\") else p


def main(source_dir: Path, scope: str) -> None:
    out_dir = Path(__file__).parent
    entries = []
    for p in sorted(source_dir.rglob("*.md")):
        size = winlong(p).stat().st_size
        tier, reason = tier_for(p, size)
        sha = hashlib.sha256(winlong(p).read_bytes()).hexdigest()
        rel = str(p.relative_to(source_dir.parent))
        segs = re.split(r"[\\/]", rel)
        in_archive = any(s.startswith("99 ") or s.startswith("99_") or s.lower().endswith("archive") or s.lower() == "archive" or s.lower() == "deprecated" for s in segs)
        entries.append({
            "path": rel, "size": size, "sha256": sha,
            "tier": tier, "reason": reason, "archive": in_archive,
        })

    (out_dir / f"triage-{scope}.json").write_text(
        json.dumps(entries, indent=1), encoding="utf-8")

    tiers = {"ingest": [], "summarize-only": [], "skip": []}
    for e in entries:
        tiers[e["tier"]].append(e)

    lines = [f"# Triage report: {scope}", ""]
    lines.append(f"Total .md files: {len(entries)}, "
                 f"total size: {sum(e['size'] for e in entries) // 1024 // 1024} MB")
    for t in ("ingest", "summarize-only", "skip"):
        rows = tiers[t]
        arch = sum(1 for e in rows if e["archive"])
        kb = sum(e["size"] for e in rows) // 1024
        lines += ["", f"## {t}: {len(rows)} files ({kb:,} KB, {arch} in 99 Archive)", ""]
        for e in sorted(rows, key=lambda x: -x["size"]):
            flag = " [ARCHIVE]" if e["archive"] else ""
            why = f" — {e['reason']}" if e["reason"] else ""
            lines.append(f"- {e['size'] // 1024:>5} KB  {e['path']}{why}{flag}")
    (out_dir / f"triage-{scope}-report.md").write_text(
        "\n".join(lines), encoding="utf-8")

    print(f"files={len(entries)} ingest={len(tiers['ingest'])} "
          f"summarize={len(tiers['summarize-only'])} skip={len(tiers['skip'])}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
