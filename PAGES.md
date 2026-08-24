# Cloudflare Pages

Plain static HTML at the repository root. No build step.

| Setting | Value |
|---|---|
| Production branch | `main` |
| Build command | *(leave empty)* |
| Build output directory | `/` (root) |

`index.html` is the whole site: what the tool does, the animated build sequence,
and the copy-paste setup prompt. It is self-contained, with no external requests,
and adapts to the visitor's light or dark theme.

To change the prompt visitors copy, edit the `#promptText` block.
