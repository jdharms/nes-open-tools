# Architecture Decision Records

> Intro, "When to write one" written by jdharms.
> Remainder written by Claude.
> The index is primarily maintained by AI agents.

Each record here captures one decision: what forced it, what was chosen, what was
turned down and why, and what should make us reopen it.

## When to write one

Write a record when a choice has a real alternative that someone could reasonably pick
later without knowing why it was turned down: a trade-off, an interim answer ("for
now"), or anything with a condition that should reopen it.

The `rejected` status is only for a proposed record that "lost"; it keeps
the history of that proposal rather than deleting it.  Generally this
should only be used if a `proposed` record gets *committed*.  If
we change our minds on a proposed record mid-session, we should rewrite
the record in the "positive" form of the chosen alternative.

## Format

A trimmed-down [MADR](https://adr.github.io/madr/) record, one file per decision:
`NNNN-slug.md`. The number and slug come from the filename and the title from the `#`
heading. The frontmatter is TOML between `+++` lines:

| Field | Meaning |
|-------|---------|
| `status` | `proposed`, `accepted`, `rejected`, `deprecated` or `superseded` |
| `date` | when the status last changed |
| `area` | `rom`, `patches`, `qr`, `randomizer`, `site`, `deploy` or `tooling` |
| `permanent` | `true` when the effects can't be undone, e.g. something baked into released ROMs |
| `revisit_when` | the observable condition that should reopen the decision |
| `drafted_by` | who wrote the draft |
| `supersedes` | numbers of the records this one replaces |
| `superseded_by` | set on a replaced record once its successor is accepted |

The body has exactly these sections, in order: Context, Decision, Rejected
alternatives, Consequences, Sources. Sources cite the docs and code involved and, for
decisions made in a Claude Code session, the date and session ID prefix.

A proposed record may leave sections empty. Any other status needs every section
filled in and `revisit_when`; a rejected record is only useful for saying why. Once a record is accepted, only its status changes. Changing the
decision means writing a new record that supersedes it.

Code and docs cite a record as "ADR" followed by its four-digit number, for example
in a comment beside the constant the decision governs.

## Commands

```bash
uv run golf-adr new "Title" --area patches [--supersedes N] [--revisit-when "..."]
uv run golf-adr status N accepted       # also marks what N supersedes as superseded
uv run golf-adr index [--check]         # regenerate the table below
uv run golf-adr check                   # numbering and supersession links
```

`tests/meta/test_adrs.py` checks every record, the links between them, that this
index is current, and that every cited record exists.

## Index

<!-- adr-index:start -->
| ADR | Title | Area | Status | Permanent | Revisit when |
|-----|-------|------|--------|-----------|--------------|
| [0001](0001-one-course-per-rom.md) | One course per ROM | patches | accepted |  | Multi-course generation (devplan item 16) is scheduled, or a patch is wanted on a ROM that keeps its vanilla courses |
| [0002](0002-any-byte-written-by-two-patchstack-steps-is-an-error.md) | Any byte written by two PatchStack steps is an error | patches | accepted |  | Overlap errors start firing on deliberate, identical writes often enough to be a nuisance |
| [0003](0003-sign-in-not-required-to-generate-or-download-seeds.md) | Sign-in not required to generate or download seeds | site | accepted |  | League rounds regularly go unrecorded because players downloaded guest ROMs, and the league wants sign-in enforced |
| [0004](0004-four-bits-each-for-strokes-and-putts-in-the-qr-hole-record.md) | Four bits each for strokes and putts in the QR hole record | qr | accepted | yes | A site seed can be built without the mercy tap-in, or the QR payload protocol changes version for another reason |
| [0005](0005-the-site-reads-its-release-from-the-git-checkout-it-runs-from.md) | The site reads its release from the git checkout it runs from | site | accepted |  | The site is deployed some other way than a git checkout of its release tag, such as a container image or a built package |
| [0006](0006-a-collection-page-is-a-directory-with-one-card-per-file.md) | A collection page is a directory with one card per file | site | accepted |  | A collection needs an order other than newest date first, or entries need structure beyond a title, a date and a Markdown body |
<!-- adr-index:end -->
