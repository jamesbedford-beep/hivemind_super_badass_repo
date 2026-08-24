# export.py: build an access-scoped knowledge pack

Ships a recipient the distilled wiki for **only** the documents they can already
access, with links between out-of-scope notes scrubbed. Deterministic script: no
model tokens, so each additional recipient is effectively free.

Works against any vault with the standard layout
(`<vault>\drive\...` mirror plus `<vault>\wiki\{concepts,entities,sources}`).
Tested against both two different vault shapes.

## The two access models (this matters)

The vaults differ in where their notes come from, so granting works differently:

- **the organisation vault**: notes derive from shared drives (`01_Interventions`,
  `02_External Affairs`, `00_Operations`). Access is decided by **shared-drive
  membership**, so `--drives` is the right lever and one flag covers thousands of
  files.
- **Personal-Drive vault**: notes derive from **My Drive** and **Shared with me**. There is
  no membership to inherit; access is **per file**. You must supply the
  recipient's accessible filenames with `--list`. The script refuses to
  blanket-grant these folders unless you pass `--allow-personal-drives`, because
  doing so would export material the recipient may have no right to.

## Usage

Dry run first, always (reports what would ship, writes nothing):

```
python export.py --vault "C:\Users\you\Documents\MyVault" ^
                 --out "C:\Users\you\Documents\exports\sarah" ^
                 --drives "01_Interventions,02 External Affairs" ^
                 --dry-run
```

Real run, per-file access (the personal-Drive case):

```
python export.py --vault "C:\Users\you\Documents\SecondVault" ^
                 --out "C:\Users\you\Documents\exports\sarah" ^
                 --list recipient-files.txt --loose
```

| Flag | Meaning |
|---|---|
| `--vault` | vault to export from |
| `--out` | output folder for the pack |
| `--drives` | comma-separated shared drives the recipient is a member of |
| `--list` | text file of filenames the recipient can access, one per line, fuzzy-matched |
| `--loose` | additionally list notes whose sources are >=50% granted, for human decision (still not exported) |
| `--dry-run` | report only |
| `--allow-personal-drives` | permit blanket-granting My Drive / Shared with me (unsafe; only with separate confirmation) |

## Getting the recipient's manifest automatically (access_manifest)

You do not have to ask the recipient for anything in the shared-drive case. This
checks their access for you, live, using the rclone remote's existing read-only
token (no new credentials):

```
.\access_manifest.ps1 -Vault "C:\Users\you\Documents\MyVault" `
                      -Email katie@example.org -Remote gdrive -Out katie-manifest.txt
```

It reports per shared drive whether that person is a member, writes a manifest of
every source document behind the wiki they can access, and tells you how many
wiki notes that covers. Feed the manifest straight to `export.py --list`.

**It verifies every file individually, not just drive membership.** This matters:
folders inside a shared drive carry their own permissions, so a drive member can
be blocked from a subfolder, and non-members can hold access to single folders.
Observed on the real corpus: one teammate is a member of `01_Interventions` yet
cannot open the 8 documents in its `Fund Scoping` folder. Membership alone would
have shipped distillations of restricted fundraising material. Files whose
permissions cannot be resolved are excluded rather than assumed.

Verified behavior: a real member returns their accessible docs; a non-existent
address at the same domain returns zero access; restricted folders are reported
as denied by name. Results are per-person and per-file, not domain-wide guesses.

`--no-verify-files` falls back to membership only. Faster, but it can over-grant,
so use it only for a rough estimate, never for a pack you intend to send.

Without an email you can skip the API entirely and just assert membership:

```
python access_manifest.py --vault "...\MyVault" --member-of "01_Interventions,02 External Affairs"
```

**Always use the .ps1 wrapper on Windows with Microsoft Store Python.** Store
Python virtualizes `%APPDATA%`, so an rclone process spawned from Python reads a
redirected copy of `rclone.conf` and can report the wrong remotes. The wrapper
fetches the token in PowerShell (not virtualized) and passes it in.

Limitation: files in **Shared with me** are owned by other people, so their
permissions cannot be audited by you. The tool reports them as not covered.
Exclude them, or confirm with the recipient.

## How to get the recipient's file list manually

Ask them for **full filenames with extensions** (not display titles); it
materially improves match rates. If they run the mirror pipeline themselves, this
gets them the list:

```
Get-ChildItem "$env:USERPROFILE\Documents\<their-vault>\drive" -Recurse -File -Filter *.md |
  ForEach-Object { $_.Name } | Set-Content recipient-files.txt -Encoding utf8
```

Matching is fuzzy: it normalizes case, `Copy of ` prefixes, `.docx.md`/`.pdf.md`
conversion suffixes, `vShared`/`vInternal`/`[external]` markers, `(1)` duplicates,
and fullwidth unicode punctuation.

## What it guarantees

- **Strict provenance:** a note ships only if EVERY document in its frontmatter
  `source:` list is accessible to the recipient. One inaccessible source excludes
  the note, because merged content cannot be safely split.
- **Always-excluded personal data:** patterns in `sensitive-excludes.txt`
  (hiring, candidate assessments, compensation, donor wealth profiling) are
  dropped regardless of access. Add new patterns there as you find them.
- **No dangling links:** links to out-of-scope notes become plain text, never
  broken wikilinks, because a dead link still leaks the target's title. The run
  verifies `unresolved links after scrub = 0` and reports it.
- **Traceable:** matching source documents are copied into the pack under the
  same `drive\...` relative paths, so every note's citation resolves for the
  recipient.

## What you must do by hand

Read `EXPORT-REPORT.txt` in the output folder before sending:

1. **Skim the flagged notes.** Body text sometimes names an out-of-scope
   document; scrubbing cannot catch prose. The report lists exactly which notes
   and which titles, so this takes minutes.
2. **Check the review candidates** (with `--loose`) if yield looks thin.
3. **Sanity-check the counts.** A surprisingly low include count usually means
   the wrong `--drives` value or a filename list of display titles.

## Known properties

- Merged entity notes (the richest ones, often drawing on 10+ sources) drop out
  when any single source is out of scope. Yield is high for recipients on all the
  same shared drives, thinner for narrow access.
- The pack is a snapshot. Re-run the command to refresh a recipient.
- Entities may come out at zero for narrow per-file exports; entity notes almost
  always span many sources.
