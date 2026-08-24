"""The team manifest: what a team's shared context consists of, plus the gate
that keeps personal data out of it."""

import json
import re
from datetime import date
from pathlib import Path

# Personal data stays out regardless of who can access the original. This is a
# separate test from Drive permissions and is not optional.
SENSITIVE = [
    (r"02 people and culture|[\/]01 hiring[\/]|people ?& ?culture", "personnel folder"),
    (r"comp benchmark|compensation|salary|pay band|offer letter", "compensation"),
    (r"candidate|work ?test|performance task|interview notes|applicant", "hiring or candidate material"),
    (r"performance review|upward feedback|probation|disciplinary|mid-?year review", "individual performance"),
    (r"prospect research|wealth screen|net worth|giving capacity|donor profile", "donor profiling"),
    (r"\bresume\b|\bcv\b|passport|visa application", "personal document"),
    (r"^private[:：]|[\/]private[:：]", "marked private"),
]

# Documents that carry knowledge, versus documents that carry logistics.
GENRE_BOOST = [
    (r"strategy|scoping|roadmap|analysis|evidence|review|framework|proposal|brief|memo|assessment", 3.0),
    (r"okr|objective|goal|plan|decision|rubric|protocol|guide|playbook", 2.0),
    (r"notes|summary|report|findings", 1.0),
]
GENRE_PENALTY = [
    (r"agenda|invitation|invite|accepted|declined|scheduling|logistics|rsvp", -4.0),
    (r"copy of|untitled|draft ?\d|test|tmp|temp|backup", -2.0),
    (r"\.xlsx\.md$|\.pptx\.md$", -0.5),
]


def flag(path):
    """Return (sensitive, reason) for a drive-relative path."""
    low = path.lower()
    for pat, reason in SENSITIVE:
        if re.search(pat, low):
            return True, reason
    return False, ""


def new_manifest(team, created_by, scopes):
    return {"team": team, "created": date.today().isoformat(), "created_by": created_by,
            "scopes": scopes, "documents": [], "excluded": [], "build": {}}


def add(man, path, reason="manual", tags=None):
    if any(d["path"] == path for d in man["documents"]):
        return False
    sens, why = flag(path)
    if sens:
        man["excluded"].append({"path": path, "reason": f"sensitivity:{why}"})
        return False
    man["documents"].append({"path": path, "added_by": reason, "tags": tags or []})
    return True


def remove(man, path):
    n = len(man["documents"])
    man["documents"] = [d for d in man["documents"] if d["path"] != path]
    return len(man["documents"]) < n


def estimate(man, sizes):
    """Rough build cost. Derived from the reference run: ~700 docs, ~18 MB of
    text, ~40M tokens end to end, so ~2.2M tokens per MB of source text."""
    total_bytes = sum(sizes.get(d["path"], 0) for d in man["documents"])
    mb = total_bytes / (1024 * 1024)
    tokens = int(mb * 2_200_000)
    return {"documents": len(man["documents"]), "mb": round(mb, 1),
            "est_tokens": tokens, "est_hours": round(max(0.2, mb * 0.35), 1)}


def save(man, path):
    Path(path).write_text(json.dumps(man, indent=1, ensure_ascii=True), encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
