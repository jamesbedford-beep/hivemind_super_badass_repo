# the organisation Knowledge Vault

This folder is a local, read-only mirror of your Google Drive (My Drive, shared drives you're a member of, and Shared with me), synced nightly and converted to markdown.

## Layout

- `drive/` — the Drive mirror. NEVER edit or write files here; the nightly sync overwrites/deletes local changes. Treat as read-only source material.
- `notes/` — your own notes. Safe to create and edit files here.
- `_pipeline/` — sync scripts and logs. Check `_pipeline/logs/` if content seems stale or missing.

## Searching

- Google Docs are native `.md` files
- Uploaded Office/PDF files appear twice: the original (e.g. `report.docx`) and a converted sibling (`report.docx.md`). Search the `.md` versions; cite the original.
- Content is at most one day old. For anything newer, or for files excluded from sync (media, files >50 MB, view-only-restricted files), use a Google Drive connector.
- Shared-with-me duplicates of shared-drive files are removed; the shared-drive copy is canonical.
