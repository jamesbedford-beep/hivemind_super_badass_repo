"""Remove files under 'Shared with me' that duplicate content elsewhere in the mirror.

Items shared with you individually often also live in a shared drive you're a
member of. The shared-drive copy is canonical; the 'Shared with me' copy is
deleted locally. Matching is by exact content hash (size prefilter first), so
only true byte-for-byte duplicates are removed. Zero-byte files are ignored.
"""

import hashlib
import sys
from pathlib import Path

SWM_DIRNAME = "Shared with me"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(root: Path) -> None:
    swm = root / SWM_DIRNAME
    if not swm.is_dir():
        print("no 'Shared with me' folder, nothing to dedupe")
        return

    canonical_by_size: dict[int, list[Path]] = {}
    for p in root.rglob("*"):
        if p.is_file() and swm not in p.parents:
            size = p.stat().st_size
            if size > 0:
                canonical_by_size.setdefault(size, []).append(p)

    hashed: dict[int, set[str]] = {}
    removed = kept = 0
    for p in list(swm.rglob("*")):
        if not p.is_file():
            continue
        size = p.stat().st_size
        if size == 0 or size not in canonical_by_size:
            kept += 1
            continue
        if size not in hashed:
            hashed[size] = {digest(c) for c in canonical_by_size[size]}
        if digest(p) in hashed[size]:
            p.unlink()
            removed += 1
        else:
            kept += 1

    # Clear out directories emptied by deduplication
    for d in sorted((d for d in swm.rglob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()

    print(f"deduped={removed} kept={kept}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
