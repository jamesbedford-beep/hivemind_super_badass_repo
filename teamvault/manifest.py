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
    (r"\bprivate\b|\bconfidential\b|\bpersonal\b|\bdo not share\b|\bnot for circulation\b",
     "marked private"),
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
            "scopes": scopes, "documents": [], "excluded": [], "build": {},
            # people whose documents settle a disagreement, e.g. the person who
            # owns a strategy. Matched against the Drive owner's address.
            "priority_authors": []}


def unverifiable(man):
    """Documents that carry no Drive permissions, so cannot be access checked.

    Notes built from these reach everyone who installs the bundle. A folder on
    somebody's laptop has no sharing model to consult, so there is nothing to
    check against and no honest way to filter per person.
    """
    return [d for d in man["documents"] if d.get("source") == "local"]


def add(man, path, reason="manual", tags=None, source="drive", meta=None):
    if any(d["path"] == path for d in man["documents"]):
        return False
    sens, why = flag(path)
    if sens:
        man["excluded"].append({"path": path, "reason": f"sensitivity:{why}"})
        return False
    doc = {"path": path, "added_by": reason, "tags": tags or [], "source": source,
           "authority": "normal"}
    # provenance travels with the document so the ingestion step can stamp it
    # into each note's frontmatter without going back to Drive
    for k in ("modified", "created", "author", "starred", "audience", "version", "genre"):
        if meta and meta.get(k) not in (None, ""):
            doc[k] = meta[k]
    man["documents"].append(doc)
    return True


def set_authority(man, path, level):
    """Mark a document authoritative, normal, or superseded."""
    if level not in ("authoritative", "normal", "superseded"):
        raise ValueError("unknown authority level: " + str(level))
    for d in man["documents"]:
        if d["path"] == path:
            d["authority"] = level
            return True
    return False


def remove(man, path):
    n = len(man["documents"])
    man["documents"] = [d for d in man["documents"] if d["path"] != path]
    return len(man["documents"]) < n


# What fraction of a file's bytes is actually text, measured by pairing 692
# originals in a real Drive mirror against the markdown convert.py produced from
# them (median ratio per format). File size is a terrible proxy for text volume:
# a PowerPoint is images and layout almost all the way down.
TEXT_FRACTION = {
    ".xlsx": 0.43, ".docx": 0.15, ".pdf": 0.044, ".pptx": 0.003,
    ".md": 1.0, ".txt": 1.0, ".csv": 0.95, ".json": 1.0,
}
DEFAULT_FRACTION = 0.3          # unknown binary format, assume mostly not text

# Native Google Docs have no size until they are exported, and rclone reports
# -1. Counting them as zero made the estimate collapse on exactly the documents
# that matter most. 17.5 kB is the median exported size across 725 of them in a
# real vault, so it stands in until the real file exists on disk.
UNKNOWN_DOC_BYTES = 17542
BYTES_PER_TOKEN = 4             # ~4 characters per token for English prose

# Reading a document costs far more than the document itself: every note is
# written by an agent carrying conventions and prior context, and the linking
# pass re-reads what is already filed.
#
# This multiplier is the weakest number here. It comes from a single run that
# was never reconciled against a bill, and that run's ledger records 193
# documents, not the ~700 it was described against. Treat the result as an
# order of magnitude and quote the floor alongside it.
PIPELINE_MULTIPLIER = 8.5

# Share of total tokens that is output rather than input. Distillation is
# read-heavy: long sources in, short notes out.
OUTPUT_SHARE = 0.15

# USD per million tokens, from platform.claude.com/docs/en/about-claude/pricing
# checked 2026-08-24. Update PRICES_CHECKED when these are re-verified.
PRICES_CHECKED = "2026-08-24"
PRICES = {
    "Sonnet 5": {"in": 2.0, "out": 10.0},
    "Opus 5": {"in": 5.0, "out": 25.0},
}


def text_bytes_for(path, size, vault=None):
    """Best estimate of how much readable text a file holds.

    If the mirror already converted it, the markdown sibling is measured
    directly and no guessing is involved.
    """
    if vault:
        md = Path(vault) / "drive" / (path + ".md")
        try:
            if md.is_file():
                return md.stat().st_size, True
        except OSError:
            pass
    if not size or size < 0:
        return UNKNOWN_DOC_BYTES, False
    ext = Path(path).suffix.lower()
    return int(size * TEXT_FRACTION.get(ext, DEFAULT_FRACTION)), False


def estimate(man, sizes, vault=None):
    """Build cost, derived from text volume rather than file size."""
    text_bytes, raw_bytes, measured = 0, 0, 0
    for d in man["documents"]:
        size = sizes.get(d["path"], 0)
        raw_bytes += max(size, 0)
        tb, exact = text_bytes_for(d["path"], size, vault)
        text_bytes += tb
        measured += 1 if exact else 0

    text_tokens = text_bytes / BYTES_PER_TOKEN
    tokens = int(text_tokens * PIPELINE_MULTIPLIER)

    def blended(tok, pr):
        return round(tok / 1e6 * ((1 - OUTPUT_SHARE) * pr["in"]
                                  + OUTPUT_SHARE * pr["out"]), 2)

    # the floor is what it costs to read every document once, with no agent
    # overhead and no linking. It is arithmetic rather than estimate, so it is
    # the number to trust when the estimate looks surprising.
    costs = {name: blended(tokens, pr) for name, pr in PRICES.items()}
    floor = {name: round(text_tokens / 1e6 * pr["in"], 2) for name, pr in PRICES.items()}
    return {
        "documents": len(man["documents"]),
        "unverifiable": len(unverifiable(man)),
        "authoritative": sum(1 for d in man["documents"]
                             if d.get("authority") == "authoritative"),
        "mb": round(raw_bytes / (1024 * 1024), 1),
        "text_mb": round(text_bytes / (1024 * 1024), 2),
        "measured": measured,
        "est_tokens": tokens,
        "est_hours": round(max(0.2, text_bytes / (1024 * 1024) * 0.8), 1),
        "costs": costs,
        "floor": floor,
        "floor_tokens": int(text_tokens),
        "prices_checked": PRICES_CHECKED,
    }


def save(man, path):
    Path(path).write_text(json.dumps(man, indent=1, ensure_ascii=True), encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
