"""Free, deterministic lint pass over the wiki. Report-only by default.

Scans concepts/entities/sources for: unresolved wikilinks, orphan notes,
em-dashes, frontmatter/JSON validity, and status:conflict notes. Builds
ledger.json from manifests. Writes a human-readable conflicts summary.
"""

import json
import re
import sys
from pathlib import Path

WIKI = Path(r"C:\Users\you\Documents\MyVault\wiki")
DIRS = ["concepts", "entities", "sources"]
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def parse_fm(text):
    m = FM_RE.match(text)
    fm = {"title": None, "uid": None, "aliases": [], "status": "clean"}
    if not m:
        return fm, False
    body = m.group(1)
    for line in body.splitlines():
        if line.startswith("title:"):
            fm["title"] = line.split(":", 1)[1].strip()
        elif line.startswith("uid:"):
            fm["uid"] = line.split(":", 1)[1].strip()
        elif line.startswith("status:"):
            fm["status"] = line.split(":", 1)[1].strip()
    am = re.search(r"aliases:\s*\[(.*?)\]", body)
    if am:
        fm["aliases"] = [a.strip().strip('"\'') for a in am.group(1).split(",") if a.strip()]
    else:
        ab = re.search(r"aliases:\s*\n((?:\s*-\s*.+\n?)+)", body)
        if ab:
            fm["aliases"] = [l.split("-", 1)[1].strip().strip('"\'') for l in ab.group(1).splitlines() if l.strip()]
    return fm, True


def main():
    notes = {}
    # root-level notes (maps of content, Start here, etc.) count too: their
    # outbound links are what absorb orphans.
    roots = [p for p in WIKI.glob("*.md") if p.name not in ("log.md",)]
    for p in roots:
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, ok = parse_fm(text)
        notes[p.stem] = {"path": p, "fm": fm, "text": text, "has_fm": ok}
    for d in DIRS:
        for p in (WIKI / d).glob("*.md"):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm, ok = parse_fm(text)
            notes[p.stem] = {"path": p, "fm": fm, "text": text, "has_fm": ok}

    targets = set()
    for stem, n in notes.items():
        targets.add(stem.lower())
        for a in n["fm"]["aliases"]:
            targets.add(a.lower())
        targets.add(("source - " + stem).lower())

    unresolved, inbound, emdash, no_fm, conflicts = {}, {s: 0 for s in notes}, [], [], []
    for stem, n in notes.items():
        if not n["has_fm"]:
            no_fm.append(stem)
        if n["fm"]["status"] == "conflict":
            conflicts.append(stem)
        if "—" in n["text"]:
            emdash.append(stem)
        for m in LINK_RE.finditer(n["text"]):
            tgt = m.group(1).split("|")[0].split("#")[0].strip()
            key = tgt.lower()
            if key in targets or ("source - " + key) in targets:
                if tgt in notes:
                    inbound[tgt] = inbound.get(tgt, 0) + 1
            else:
                unresolved.setdefault(tgt, []).append(stem)

    orphans = [s for s, c in inbound.items() if c == 0]

    # Build ledger from manifests
    manifests = list((WIKI / "_ingest" / "manifests").glob("*.json"))
    ledger = {}
    for mf in manifests:
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            ledger[m.get("slug", mf.stem)] = {"source": m.get("source", ""), "notes": len(m.get("notes", [])), "downgraded": m.get("downgraded", False)}
        except Exception:
            pass
    (WIKI / "_ingest" / "ledger.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=True), encoding="utf-8")

    # concept-index validity
    try:
        ci = json.loads((WIKI / "_ingest" / "concept-index.json").read_text(encoding="utf-8"))
        ci_status = f"valid, {len(ci)} entries"
    except Exception as e:
        ci_status = f"INVALID: {e}"

    # Conflicts summary doc
    lines = ["# Conflicts to adjudicate", "", f"{len(conflicts)} notes flagged status:conflict. Each has a callout naming both claims and sources.", ""]
    for s in sorted(conflicts):
        lines.append(f"- [[{s}]]")
    (WIKI / "Conflicts to adjudicate.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"notes scanned: {len(notes)}")
    print(f"ledger.json: {len(ledger)} sources recorded")
    print(f"concept-index.json: {ci_status}")
    print(f"notes missing frontmatter: {len(no_fm)}")
    print(f"em-dash notes: {len(emdash)} -> {emdash[:10]}")
    print(f"status:conflict notes: {len(conflicts)}")
    print(f"orphan notes (0 inbound): {len(orphans)}")
    print(f"distinct unresolved link targets: {len(unresolved)}")
    top = sorted(unresolved.items(), key=lambda kv: -len(kv[1]))[:15]
    for tgt, srcs in top:
        print(f"  [{len(srcs)}x] {tgt}")


if __name__ == "__main__":
    main()
