+++
status = "accepted"
date = 2026-09-29
area = "site"
permanent = false
revisit_when = "Players need saved settings that follow them across browsers while signed out, or entries start recording the bag a round was played with"
drafted_by = "Claude"
supersedes = []
+++

# Saved download settings live in a cookie and on the account, not in entries

## Context

Players mostly want the same name, bag and options on every seed, but the seed page's
download form started from the vanilla settings every time (GitHub issue 15). Most
downloads are by signed-out players, so anything that only works when signed in misses
most of them. A signed-in player may also download from several browsers.

The site already records something close: an entry holds the name and bag of a player's
latest download of one seed. But entries exist only for signed-in players, hold no BGM,
swing, putt or spin, and their bag is the bag that seed's club rules allowed, not the bag
the player prefers.

## Decision

- Saved settings are one versioned JSON record (`SavedSettings` in `server/forms.py`):
  name, clubs, BGM, swing, putt, spin. Reading is lenient: a missing, unknown or invalid
  field reads as vanilla. A new setting is a new optional field, not a new version.
- Every successful download saves the record, by the saving rule (`to_save`): name and
  BGM always; the bag only from a seed with the default club rules; swing, putt and spin
  only from a seed whose finish ABI can write them.
- It is saved in the `golf_download` cookie for every player, HttpOnly, SameSite=lax,
  Secure on HTTPS, lasting a year from each download. For a signed-in player it is also
  saved in the `download_settings` table, one row per user.
- The seed page's form starts from, highest first: this seed's entry (name and clubs
  only), the account's row, the cookie, the vanilla settings. Every source is fitted to the
  seed's club rules and ABI.
- `/me` edits the account's settings and has a "forget my settings" action that deletes
  the row and expires the cookie in that browser.

## Rejected alternatives

- **The latest entry as the source.** No help to signed-out players, no options, and its
  bag is the one a restricted seed allowed rather than the player's preference.
- **Browser storage (`localStorage`).** The form would then need `download.js` to fill
  it, and the server could not render the fitted form; the cookie reaches the server
  with the page request.
- **Cookie only.** A signed-in player would start from vanilla on every new browser.
- **Account only.** Signed-out players would get nothing.

## Consequences

- A signed-in player's settings follow them across browsers; a guest's stay in the browser
  that downloaded.
- The cookie is untrusted input and is validated like a form submission. A cookie that
  fails to decode reads as vanilla and is replaced by the next download.
- Once a signed-in player has a row, the account wins over that browser's cookie. Signing
  out on a browser keeps its cookie, which the last download there wrote.
- "Forget" clears the account and the current browser only; another browser keeps its
  cookie until its next download.
- The privacy policy has to list the `golf_download` cookie.

## Sources

- `docs/planning/download_settings.md`, "Decisions" and "Storage".
- `server/forms.py`, `server/download_settings.py`, `server/app.py`.
- GitHub issues 4 and 15. Planning session with Claude, 2026-09-28.
