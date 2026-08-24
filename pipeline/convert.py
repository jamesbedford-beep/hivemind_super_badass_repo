"""Convert non-markdown documents in the vault mirror to .md siblings.

A file like report.docx becomes report.docx.md alongside it, so provenance
is obvious and names can't collide with markdown exported from Google Docs.
Skips files whose .md is already newer than the source; deletes orphaned
.md conversions whose source file disappeared from Drive.
"""

import sys
from pathlib import Path

from markitdown import MarkItDown

CONVERT_EXTS = {".docx", ".pptx", ".xlsx", ".pdf"}

# Stamped on every file this script generates. Orphan cleanup only deletes
# marked files, so markdown that came from Drive itself is never touched.
MARKER = "<!-- converted by vault pipeline -->\n\n"


def main(root: Path) -> None:
    md = MarkItDown()
    converted = skipped = failed = removed = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        # Remove orphaned conversions (source gone from Drive)
        if path.suffix == ".md":
            source = path.with_name(path.name[:-3])
            if source.suffix.lower() in CONVERT_EXTS and not source.exists():
                try:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        generated = f.readline().startswith("<!-- converted by")
                except OSError:
                    generated = False
                if generated:
                    path.unlink()
                    removed += 1
            continue

        if path.suffix.lower() not in CONVERT_EXTS:
            continue

        out = path.with_name(path.name + ".md")
        if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
            skipped += 1
            continue

        try:
            result = md.convert(str(path))
            out.write_text(MARKER + result.text_content, encoding="utf-8")
            converted += 1
        except Exception as exc:  # noqa: BLE001 - log and keep going
            print(f"FAIL {path}: {exc}")
            failed += 1

    print(f"converted={converted} skipped={skipped} failed={failed} orphans_removed={removed}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
