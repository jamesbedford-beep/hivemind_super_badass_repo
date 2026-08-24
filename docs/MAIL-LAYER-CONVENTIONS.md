# Mail layer: conventions

Distilled email threads, kept **outside** `wiki/` on purpose.

Email is categorically more sensitive than Drive: it contains other people's
confidential messages, personal contact details, HR and compensation matters,
and material from outside the organisation entirely. During the Drive ingestion, four
separate safeguards each caught personal data that slipped past the previous
one. Email would be worse.

So the rule here is inverted from the wiki: **everything in this folder is
private by default and is excluded from every export unless explicitly cleared.**

## Layout

- `threads/` one note per email thread, named `YYYY-MM-DD Subject.md`
- Nothing here is linked into `wiki/`. Claude can read both; exports cannot.

## Frontmatter (every note)

```yaml
---
type: mail-thread
title: <subject>
uid: <kebab-slug>
date: <YYYY-MM-DD of first message>
participants: [<email>, ...]
visibility: private          # never anything else without a deliberate decision
tags: [email, private]
status: clean
thread_id: <gmail thread id>
---
```

## Content rules

- Open with `> [!warning] Private. Email thread, excluded from all exports.`
- Keep the substance: decisions, commitments, facts, figures, links.
- Strip quoted reply chains, signatures, tracking pixels, and boilerplate.
- **Content is preserved in full, including sensitive material** (owner's
  decision, 2026-08-05). This is a single-reader local layer: the protection is
  that nothing here is ever exported, not that content is redacted. Comp,
  candidate, personal and confidential threads are all in scope.
- The safeguard that must never be weakened is the export exclusion: every note
  carries `visibility: private`, lives outside `wiki/`, and is dropped by
  `sensitive-excludes.txt`. If mail is ever shared, that is the thing to check.
- Preserve evidence-strength language exactly as written, and attribute claims
  to the person who made them ("Karen reports...", not "it is the case that...").

## What is worth ingesting

Include: substantive decisions, partner and funder discussions, intros with
context, strategy debates, commitments made, useful external information.

Exclude: calendar invitations and acceptances, automated notifications, security
alerts, newsletters, promotions, purely logistical scheduling, and any thread
whose subject begins with `Accepted:`, `Declined:`, `Invitation:`, `Updated
invitation:`, or `Canceled:`.
