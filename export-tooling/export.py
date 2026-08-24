"""Export an access-scoped slice of a knowledge vault for a recipient.

Vault-agnostic: works against any vault with the standard layout
(<vault>\\drive\\... mirror + <vault>\\wiki\\{concepts,entities,sources}).

Selection rule (strict, default): a wiki note is exported only if EVERY document
in its frontmatter `source:` list is one the recipient can access. Notes drawing
on even one inaccessible source are held back, because their content is
interleaved and cannot be safely split.

Always excluded regardless of access: anything matching sensitive-excludes.txt
(person assessments, hiring, compensation, donor profiling). Access is not the
only test; personal data stays out.

Usage:
  python export.py --vault "C:\\Users\\me\\Documents\\MyVault" ^
                   --out "C:\\Users\\me\\Documents\\exports\\sarah" ^
                   --drives "01_Interventions,02_External Affairs" ^
                   [--list recipient-files.txt] [--loose] [--dry-run]

  --drives  comma-separated shared drives the recipient is a member of. Grants
            every mirrored file under those drive folders.
  --list    optional text file of filenames the recipient can access (one per
            line, full filenames preferred). Used for items outside the granted
            drives (their My Drive, individually shared files). Fuzzy-matched.
  --loose   also write a review list of notes whose sources are MOSTLY granted
            (they are still not exported; the list is for human decision).
  --dry-run report only, write nothing.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

NOTE_DIRS = ["concepts", "entities", "sources"]
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
CONV_EXT = re.compile(r"\.(docx|pptx|xlsx|pdf)\.md$", re.I)


def winlong(p: Path) -> Path:
    s = str(p)
    return Path("\\\\?\\" + s) if not s.startswith("\\\\?\\") else p


def norm_name(name: str) -> str:
    """Aggressive normalization for fuzzy filename matching."""
    n = name.lower()
    n = CONV_EXT.sub("", n)
    n = re.sub(r"\.md$", "", n)
    n = re.sub(r"^(copy of |copia de )+", "", n)
    n = re.sub(r"\bv?(shared|internal|external|pdf)\b", "", n)
    n = n.replace("\uff1a", ":").replace("\uff0f", "/").replace("\uff5c", "|")
    n = re.sub(r"\(\d+\)", "", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def read_notes(vault: Path):
    notes = {}
    for d in NOTE_DIRS:
        for p in (vault / "wiki" / d).glob("*.md"):
            text = winlong(p).read_text(encoding="utf-8", errors="replace")
            m = FM_RE.match(text)
            fm_raw = m.group(1) if m else ""
            sources = []
            sm = re.search(r"source:\s*\n((?:\s*-\s*.+\n?)+)", fm_raw)
            if sm:
                for line in sm.group(1).splitlines():
                    v = line.split("-", 1)[1].strip().strip('<>"\'') if "-" in line else ""
                    if v:
                        sources.append(v)
            aliases = []
            am = re.search(r"aliases:\s*\[(.*?)\]", fm_raw)
            if am:
                aliases = [a.strip().strip('"\'') for a in am.group(1).split(",") if a.strip()]
            else:
                ab = re.search(r"aliases:\s*\n((?:\s*-\s*.+\n?)+)", fm_raw)
                if ab:
                    aliases = [l.split("-", 1)[1].strip().strip('"\'') for l in ab.group(1).splitlines() if l.strip()]
            notes[p.stem] = {"path": p, "dir": d, "text": text, "sources": sources, "aliases": aliases}
    return notes


def src_rel(s: str) -> str:
    """Frontmatter source -> mirror-relative path (drive/ stripped)."""
    s = s.replace("/", "\\").strip()
    s = re.sub(r"^(\.\.\\)+", "", s)
    s = re.sub(r"^drive\\", "", s, flags=re.I)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--drives", default="")
    ap.add_argument("--list", default=None)
    ap.add_argument("--loose", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-personal-drives", action="store_true",
                    help="permit blanket-granting 'My Drive' / 'Shared with me' (per-file access; unsafe by default)")
    a = ap.parse_args()

    vault, out = Path(a.vault), Path(a.out)
    if not (vault / "wiki").is_dir():
        sys.exit(f"no wiki found at {vault}\\wiki")

    granted_drives = [d.strip() for d in a.drives.split(",") if d.strip()]

    # "My Drive" and "Shared with me" are PER-FILE access, not membership-based.
    # Blanket-granting them would export notes derived from documents the
    # recipient may have no right to. Require an explicit opt-in.
    PERSONAL = {"my drive", "shared with me"}
    risky = [d for d in granted_drives if d.lower() in PERSONAL]
    if risky and not a.allow_personal_drives:
        sys.exit(
            f"refusing to blanket-grant {risky}: these are per-file access, not shared-drive\n"
            "membership. Supply the recipient's accessible filenames via --list instead, or\n"
            "pass --allow-personal-drives if you have separately confirmed they can open\n"
            "every file in those folders.")
    here = Path(__file__).parent
    sens_pat = []
    sf = here / "sensitive-excludes.txt"
    if sf.exists():
        for line in sf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                sens_pat.append(line.lower())

    recipient_norms = set()
    if a.list:
        for line in Path(a.list).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                recipient_norms.add(norm_name(Path(line).name))

    notes = read_notes(vault)

    def is_sensitive(rel: str) -> bool:
        r = rel.lower()
        return any(pat in r for pat in sens_pat)

    def granted(rel: str) -> bool:
        top = rel.split("\\")[0]
        if granted_drives and top in granted_drives:
            return True
        return norm_name(Path(rel).name) in recipient_norms

    included, excluded, review, sensitive_hits = {}, {}, [], []
    for stem, n in notes.items():
        rels = [src_rel(s) for s in n["sources"]]
        if not rels:
            excluded[stem] = "no source provenance"
            continue
        if any(is_sensitive(r) for r in rels):
            excluded[stem] = "sensitive source"
            sensitive_hits.append(stem)
            continue
        ok = [granted(r) for r in rels]
        if all(ok):
            included[stem] = n
        else:
            excluded[stem] = f"{ok.count(False)}/{len(ok)} sources not accessible"
            if a.loose and ok.count(True) / len(ok) >= 0.5:
                review.append((stem, excluded[stem]))

    # resolvable targets among included notes (filename + aliases + "Source - X")
    targets = {}
    for stem, n in included.items():
        targets[stem.lower()] = stem
        targets[f"source - {stem}".lower()] = stem
        for al in n["aliases"]:
            targets.setdefault(al.lower(), stem)

    excluded_titles = {stem.lower() for stem in excluded}
    scrubbed_links, prose_flags = 0, []

    def scrub(text: str):
        nonlocal scrubbed_links
        def rep(m):
            nonlocal scrubbed_links
            raw = m.group(1)
            tgt = raw.split("|")[0].split("#")[0].strip()
            disp = raw.split("|")[-1].strip() if "|" in raw else tgt
            if tgt.lower() in targets:
                return m.group(0)
            scrubbed_links += 1
            return disp  # plain text, never a dangling link
        return LINK_RE.sub(rep, text)

    report = []
    report.append(f"vault: {vault}")
    report.append(f"granted drives: {granted_drives or '(none)'}")
    report.append(f"recipient list entries: {len(recipient_norms)}")
    report.append(f"wiki notes scanned: {len(notes)}")
    report.append(f"INCLUDED: {len(included)}")
    report.append(f"EXCLUDED: {len(excluded)}  (sensitive: {len(sensitive_hits)})")
    if a.loose:
        report.append(f"review candidates (>=50% sources granted): {len(review)}")

    if a.dry_run:
        print("\n".join(report))
        by_reason = {}
        for stem, why in excluded.items():
            by_reason[why] = by_reason.get(why, 0) + 1
        print("\nexclusion reasons:")
        for why, c in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            print(f"  {c:>5}  {why}")
        # Dry-run still writes the actual included-note list (relative wiki
        # paths, e.g. "concepts/Foo.md") next to --out, so you can inspect who
        # gets what before copying any files or scrubbing any links.
        list_path = Path(str(a.out) + "-included-notes.txt")
        list_path.parent.mkdir(parents=True, exist_ok=True)
        lines = sorted(f"{n['dir']}/{stem}.md" for stem, n in included.items())
        list_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nincluded-note list written to {list_path}")
        return

    # write package
    for d in NOTE_DIRS:
        (out / "wiki" / d).mkdir(parents=True, exist_ok=True)
    copied_sources, missing_sources = set(), []
    for stem, n in included.items():
        text = scrub(n["text"])
        low = text.lower()
        hit = [t for t in excluded_titles if len(t) > 24 and t in low]
        if hit:
            prose_flags.append((stem, hit[:3]))
        (out / "wiki" / n["dir"] / f"{stem}.md").write_text(text, encoding="utf-8")
        for s in n["sources"]:
            rel = src_rel(s)
            src = vault / "drive" / rel
            if not winlong(src).exists():
                missing_sources.append(rel)
                continue
            dst = out / "drive" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel not in copied_sources:
                shutil.copy2(winlong(src), winlong(dst))
                copied_sources.add(rel)

    # verify: no unresolved links remain in the exported wiki
    unresolved = set()
    for d in NOTE_DIRS:
        for p in (out / "wiki" / d).glob("*.md"):
            for m in LINK_RE.finditer(p.read_text(encoding="utf-8")):
                t = m.group(1).split("|")[0].split("#")[0].strip()
                if t.lower() not in targets:
                    unresolved.add(t)

    (out / "CLAUDE.md").write_text(
        "# Knowledge pack\n\n"
        "`drive/` holds source documents (read-only reference). `wiki/` holds distilled,\n"
        "linked notes: `concepts/`, `entities/`, and `sources/` (one summary per source doc).\n\n"
        "Every note's frontmatter `source:` field points at its original document under\n"
        "`drive/`, so claims are traceable. Open this folder as an Obsidian vault to browse\n"
        "the link graph, or point an AI coding assistant at it to search and synthesize.\n\n"
        "This is an access-scoped snapshot: it contains only material derived from documents\n"
        "the recipient can already access. Some links were converted to plain text because\n"
        "their targets fall outside that scope. It does not auto-update.\n",
        encoding="utf-8")

    report += [
        f"source docs copied: {len(copied_sources)}",
        f"links scrubbed to plain text: {scrubbed_links}",
        f"notes flagged for prose skim: {len(prose_flags)}",
        f"unresolved links after scrub (must be 0): {len(unresolved)}",
        f"missing source files (in frontmatter, absent from mirror): {len(set(missing_sources))}",
    ]
    if prose_flags:
        report.append("\nSKIM THESE (body text names an out-of-scope document):")
        report += [f"  {s} -> {h}" for s, h in prose_flags[:40]]
    if review:
        report.append("\nREVIEW CANDIDATES (not exported; >=50% of sources granted):")
        report += [f"  {s} ({why})" for s, why in review[:60]]
    (out / "EXPORT-REPORT.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\npackage written to {out}")


if __name__ == "__main__":
    main()
