+++
status = "accepted"
date = 2026-09-24
area = "site"
permanent = false
revisit_when = "A collection needs an order other than newest date first, or entries need structure beyond a title, a date and a Markdown body"
drafted_by = "Claude"
supersedes = []
+++

# A collection page is a directory with one card per file

## Context

The site needed an updates page listing its releases, each shown as a card. Markdown
pages were single files rendered into one `<article>`, which Pico draws as a card, so a
page was one big card. A release has a version and a date that are more useful as data
than as heading text: they give an order, an anchor for each release, and later perhaps a
"latest update" line elsewhere on the site.

## Decision

A directory directly under `server/content/pages/` is a collection page served at
`/pages/<directory>`. Its `_index.md` holds the page's usual frontmatter and an optional
intro. Every other `.md` file in it is an entry with a required `title`, a required TOML
local `date` and an optional `enabled`, shown as a card whose id is the file name's stem
and whose title links to that anchor. Entries are ordered newest date first, with ties
broken by file name, descending. A disabled entry is validated at startup and never
rendered. The page around the cards is not an `<article>`, so cards never nest.

## Rejected alternatives

- **Split one Markdown file into cards at each `##` heading.** About a third of the work,
  and keeps a single file, but the version and date would be heading text, not data, so
  ordering, anchors and drafts would each need parsing or conventions.
- **Explicit `::: card` blocks from `mdit-py-plugins`' container plugin.** More flexible
  than either, but a new dependency and new syntax for the page authors, for layouts no
  page needs.
- **Order by `order` numbers, file name prefixes or version strings.** Each needs upkeep
  or fussy parsing that the date already provides.

## Consequences

- Adding a release is adding a file; `golf-site-new-page --entry PAGE TITLE` writes one
  dated today.
- Pages and entries have separate frontmatter schemas, and a page file and a collection
  cannot share a name.
- Collections are one level deep; a directory inside one is an error.
- The date renders through the `calendar_date` filter, and `server/static/localtime.js`
  formats a date alone in UTC so no time zone shows it as the day before.

## Sources

- `server/pages.py`, `server/templates/page.html`, `tools/new_page.py`, `server/CLAUDE.md`
- Claude Code session: 2026-09-24 `bac332b9` (cards for the updates page)
