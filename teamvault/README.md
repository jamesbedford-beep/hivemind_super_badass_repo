# Team Vault

A local web app for a team lead to curate their team's shared context once, and
ship a single bundle that sets every teammate up with an access-correct,
self-updating knowledge base.

## Run it

    cd teamvault
    python server.py --vault "C:\Users\you\Documents\TeamVault"

Starts a local server and opens your browser. Nothing is uploaded; everything
runs on this machine.

## The five steps

1. **Connect** a Google account, read-only. Consent is delegated to rclone, so
   this tool ships no OAuth client secret of its own.
2. **Curate** with ranked suggestions, each showing why it surfaced (cited by N
   notes, substantive document, near the top of its folder). Logistics,
   invitations and archives rank last.
3. **Review** before spending: estimated tokens and build time, the personal
   data gate, and a per-teammate access preview computed from real Drive
   permissions.
4. **Build** once. This is the expensive step and the lead pays it for everyone.
5. **Ship** one bundle.

## What a teammate does

    python install.py

Signs into their own Google account, works out which of the manifest's documents
they can actually open, and installs only the notes derived from those. Links to
anything they are not getting are converted to plain text, never left dangling.

This is the point of the design: the access filter runs where the credentials
are, so nobody computes a per-person export by hand and nobody receives notes
built from documents they cannot open.

## Files

| File | Role |
|---|---|
| `server.py` | local web app and API |
| `core.py` | Drive access via the rclone remote, permission checks |
| `manifest.py` | the team manifest, plus the personal-data gate |
| `suggest.py` | ranking, no model calls |
| `install.py` | the recipient-side installer and access filter |
| `static/` | the single-page UI |

## Notes for Windows

rclone is always invoked with an explicit `--config` path and decoded as UTF-8.
Microsoft Store Python virtualises `%APPDATA%`, so a child process would
otherwise read a redirected copy of `rclone.conf` with the wrong remotes, and
would fail to decode unicode filenames.
