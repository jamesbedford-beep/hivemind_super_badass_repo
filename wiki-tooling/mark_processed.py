"""Record tonight's batch in the ledger so it is never re-queued.

Runs after the ingestion agent, whatever the agent decided. A document can be
legitimately processed with no new notes (it turned out to duplicate an existing
source in a different export format, or it was skipped as sensitive). Without
this, such documents are detected as "new" every single night forever, and every
night the agent spends tokens re-deciding they are duplicates.
"""

import hashlib
import json
from pathlib import Path

WIKI = Path(__file__).resolve().parent.parent
DRIVE = WIKI.parent / "drive"
LEDGER = WIKI / "_ingest" / "ledger.json"
TONIGHT = WIKI / "_ingest" / "tonight.txt"


def winlong(p: Path) -> Path:
    s = str(p)
    return Path("\\\\?\\" + s) if not s.startswith("\\\\?\\") else p


def main():
    if not TONIGHT.exists():
        print("no tonight.txt; nothing to mark")
        return
    paths = [l.strip() for l in TONIGHT.read_text(encoding="utf-8").splitlines() if l.strip()]
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}

    added = 0
    for rel in paths:
        p = DRIVE / rel
        if not winlong(p).exists():
            continue
        try:
            h = hashlib.sha256(winlong(p).read_bytes()).hexdigest()
        except OSError:
            continue
        slug = rel.replace("\\", "__").lower()[:120]
        prior = ledger.get(slug, {})
        ledger[slug] = {"source": rel, "sha256": h,
                        "notes": prior.get("notes", 0),
                        "processed": True}
        added += 1

    LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=True), encoding="utf-8")
    TONIGHT.write_text("", encoding="utf-8")
    print(f"marked {added} documents as processed in the ledger")


if __name__ == "__main__":
    main()
