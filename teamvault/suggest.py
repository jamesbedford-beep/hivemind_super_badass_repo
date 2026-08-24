"""Rank documents a team lead probably wants, with a stated reason for each.

No model calls: every signal is computed from the file listing and, when a wiki
already exists, from how often a document is cited by existing notes.
"""

import re
from collections import defaultdict
from pathlib import Path

import manifest


def _genre_score(name):
    s, why = 0.0, []
    low = name.lower()
    for pat, w in manifest.GENRE_BOOST:
        if re.search(pat, low):
            s += w
            why.append("substantive document")
            break
    for pat, w in manifest.GENRE_PENALTY:
        if re.search(pat, low):
            s += w
            why.append("logistics or duplicate")
            break
    return s, why


def citation_counts(wiki_dir):
    """How many existing notes cite each source document."""
    counts = defaultdict(int)
    w = Path(wiki_dir) if wiki_dir else None
    if not w or not w.is_dir():
        return counts
    fm = re.compile(r"^---\n(.*?)\n---", re.S)
    for p in w.rglob("*.md"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        m = fm.match(t)
        if not m:
            continue
        sm = re.search(r"source:\s*\n((?:\s*-\s*.+\n?)+)", m.group(1))
        if not sm:
            continue
        for line in sm.group(1).splitlines():
            if "-" in line:
                v = line.split("-", 1)[1].strip().strip('<>"\'')
                counts[Path(v.replace("/", "\\")).name.lower()] += 1
    return counts


def rank(files, wiki_dir=None, limit=200):
    cites = citation_counts(wiki_dir)
    depths = [f["path"].count("\\") for f in files] or [0]
    median_depth = sorted(depths)[len(depths) // 2]

    out = []
    for f in files:
        sens, why_sens = manifest.flag(f["path"])
        score, why = _genre_score(f["name"])

        c = cites.get(f["name"].lower(), 0)
        if c:
            score += min(6.0, 1.5 * c ** 0.5)
            why.insert(0, f"cited by {c} existing note{'s' if c > 1 else ''}")

        kb = f["size"] / 1024
        if 8 <= kb <= 400:
            score += 1.5
        elif kb < 2:
            score -= 3.0
            why.append("very small")
        elif kb > 3000:
            score -= 2.0
            why.append("very large")

        if f["path"].count("\\") <= median_depth:
            score += 0.8
            why.append("near the top of its folder")

        if re.search(r"(^|[\/])(99[ _]|archive|deprecated)", f["path"], re.I):
            score -= 5.0
            why.append("archived")

        out.append({**f, "score": round(score, 2), "sensitive": sens,
                    "reason": ("blocked: " + why_sens) if sens else (", ".join(why[:2]) or "candidate"),
                    })
    out.sort(key=lambda x: -x["score"])
    return [o for o in out if not o["sensitive"]][:limit], [o for o in out if o["sensitive"]]
