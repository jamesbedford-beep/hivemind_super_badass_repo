"""Corpus-wide duplicate detection across the whole wiki (free, deterministic).

Batch-scoped merging could not see across batches, so near-duplicate notes exist
with different casing, phrasing, or acronym forms. This finds candidate clusters
and writes them for a merge pass to act on. Report-only: never edits notes.
"""

import difflib
import json
import re
from collections import defaultdict
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
DIRS = ["concepts", "entities", "sources"]
FM = re.compile(r"^---\n(.*?)\n---", re.S)

STOP = {"the", "a", "an", "of", "for", "in", "on", "to", "and", "vs", "with", "at", "by"}
ACRO = re.compile(r"\s*\(([A-Z0-9][A-Z0-9&/\-\. ]{1,12})\)\s*$")


def norm(title: str) -> str:
    t = title.lower().strip()
    t = ACRO.sub("", t)                       # drop trailing "(CHAI)"
    t = re.sub(r"[‘’']", "", t)
    t = re.sub(r"&", " and ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w not in STOP]
    words = [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words]  # crude singularize
    return " ".join(sorted(words))            # order-insensitive


def main():
    notes = []
    for d in DIRS:
        for p in (WIKI / d).glob("*.md"):
            text = p.read_text(encoding="utf-8", errors="replace")
            m = FM.match(text)
            fm = m.group(1) if m else ""
            title = p.stem
            tm = re.search(r"^title:\s*(.+)$", fm, re.M)
            if tm:
                title = tm.group(1).strip().strip('"\'')
            uid = ""
            um = re.search(r"^uid:\s*(.+)$", fm, re.M)
            if um:
                uid = um.group(1).strip()
            body = text[m.end():] if m else text
            notes.append({"stem": p.stem, "dir": d, "title": title, "uid": uid,
                          "norm": norm(title), "chars": len(body)})

    clusters = defaultdict(list)
    for n in notes:
        clusters[(n["dir"], n["norm"])].append(n)
    exact = [v for v in clusters.values() if len(v) > 1]

    # uid collisions across different filenames
    by_uid = defaultdict(list)
    for n in notes:
        if n["uid"]:
            by_uid[n["uid"]].append(n)
    uid_dupes = [v for v in by_uid.values() if len({x["stem"] for x in v}) > 1]

    # fuzzy: same dir, high title similarity, not already in an exact cluster
    seen_pairs = set()
    for v in exact:
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                seen_pairs.add(tuple(sorted((v[i]["stem"], v[j]["stem"]))))
    fuzzy = []
    by_dir = defaultdict(list)
    for n in notes:
        by_dir[n["dir"]].append(n)
    for d, group in by_dir.items():
        group.sort(key=lambda x: x["norm"])
        for i, a in enumerate(group):
            for b in group[i + 1:i + 30]:      # local window; norm-sorted keeps near titles adjacent
                key = tuple(sorted((a["stem"], b["stem"])))
                if key in seen_pairs:
                    continue
                r = difflib.SequenceMatcher(None, a["norm"], b["norm"]).ratio()
                # also treat containment as a candidate ("X" vs "X in LMICs")
                sa, sb = set(a["norm"].split()), set(b["norm"].split())
                contained = bool(sa) and bool(sb) and (sa <= sb or sb <= sa)
                if r >= 0.80 or contained:
                    seen_pairs.add(key)
                    fuzzy.append({"ratio": round(r, 3), "dir": d,
                                  "a": a["stem"], "a_chars": a["chars"],
                                  "b": b["stem"], "b_chars": b["chars"]})

    out = {
        "exact_clusters": [[{"stem": x["stem"], "dir": x["dir"], "chars": x["chars"]} for x in v] for v in exact],
        "uid_collisions": [[{"stem": x["stem"], "dir": x["dir"], "uid": x["uid"]} for x in v] for v in uid_dupes],
        "fuzzy_pairs": sorted(fuzzy, key=lambda x: -x["ratio"]),
    }
    (WIKI / "_ingest" / "dedupe-candidates.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    print(f"notes scanned: {len(notes)}")
    print(f"exact normalized-title clusters: {len(exact)} (notes involved: {sum(len(v) for v in exact)})")
    print(f"uid collisions: {len(uid_dupes)}")
    print(f"fuzzy pairs (>=0.88): {len(fuzzy)}")
    print("\ntop exact clusters:")
    for v in sorted(exact, key=lambda v: -len(v))[:12]:
        print(f"  [{v[0]['dir']}] " + "  ||  ".join(f"{x['stem']} ({x['chars']}c)" for x in v))
    print("\ntop fuzzy pairs:")
    for f in out["fuzzy_pairs"][:12]:
        print(f"  {f['ratio']} [{f['dir']}] {f['a']} ({f['a_chars']}c)  ||  {f['b']} ({f['b_chars']}c)")


if __name__ == "__main__":
    main()
