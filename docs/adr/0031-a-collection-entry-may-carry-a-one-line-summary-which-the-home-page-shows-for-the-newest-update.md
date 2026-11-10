+++
status = "accepted"
date = 2026-11-10
area = "site"
permanent = false
revisit_when = "A collection needs an order other than newest date first, entries need structure beyond a title, a date, a summary and a Markdown body, or the home page needs more than the newest update"
drafted_by = "Claude"
supersedes = [6]
+++

# A collection entry may carry a one-line summary, which the home page shows for the newest update

## Context

ADR 0006 made a collection page a directory of entries, each with a title, a date and a
Markdown body, and named a "latest update" line elsewhere on the site as a later use of
that data. The site copy review asked for that line on the home page, to show visitors
the project is active and point them at the updates. The updates' titles are only version
numbers, by design, and the footer already shows the site's release (ADR 0005), so a line
built from the title and date would say nothing new. What a newcomer needs is what the
release brought, in a few words, which no existing field holds.

## Decision

A directory directly under `server/content/pages/` is a collection page served at
`/pages/<directory>`. Its `_index.md` holds the page's usual frontmatter and an optional
intro. Every other `.md` file in it is an entry with a required `title`, a required TOML
local `date`, an optional `summary` and an optional `enabled`, shown as a card whose id is
the file name's stem and whose title links to that anchor. Entries are ordered newest date
first, with ties broken by file name, descending. A disabled entry is validated at startup
and never rendered. The page around the cards is not an `<article>`, so cards never nest.

`summary` is one line of plain text saying what the entry brought; absent or empty, the
entry has none. The home page shows the newest enabled entry of the `updates` collection
as a line linking to its card, worded by the `home.latest_update` string, which receives
the summary, the title as `version` and the date. When that entry has no summary, the
home page shows no line at all, rather than a version number the footer already shows.

## Rejected alternatives

- **The newest entry's title and date alone.** No new field, but the title is a version
  number the footer already shows, so the line would tell a visitor nothing.
- **Falling back to the title and date when the newest entry has no summary.** Same
  objection; leaving the line out until a summary is written keeps it worth reading.
- **Inline Markdown in the summary.** The line is itself a link, so links inside it
  would nest, and emphasis in one short line is not worth a second renderer setting.
- **Showing the newest entry's first paragraph.** Release notes open with whatever the
  release needs, not a summary, and a paragraph is too long for the home page.

## Consequences

- Adding a release is adding a file; `golf-site-new-page --entry PAGE TITLE` writes one
  dated today, with `summary = ""` to fill in.
- A release whose entry has no summary takes the line off the home page until one is
  written.
- Pages and entries have separate frontmatter schemas, and a page file and a collection
  cannot share a name.
- Collections are one level deep; a directory inside one is an error.
- The date renders through the `calendar_date` filter, and `server/static/localtime.js`
  formats a date alone in UTC so no time zone shows it as the day before.

## Sources

- `server/pages.py`, `server/routes/site.py`, `server/templates/home.html`,
  `server/templates/page.html`, `tools/new_page.py`, `server/CLAUDE.md`
- ADR 0006, which this replaces, and ADR 0005 (the release in the footer)
- Claude Code session: 2026-11-10 `8f585394` (site copy review, `act-latest`)
