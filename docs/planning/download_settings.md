# Saved Download Settings: Development Plan

> **Note**: This document was written by Claude, with some light edits by jdharms.
> It is the plan for the next release's download settings work: what the seed
> page's download form offers, how a player's
> choices are remembered between seeds, and the order of work.

## Goal

Players mostly want the same name, bag and options on every seed. The download form
remembers what a player last chose, fits it to each seed's club rules, and shows it
collapsed so a player who is happy with it downloads in one click. The form also gains
the new-save options the game keeps in SRAM that the site does not offer yet.

In scope:

- Four more download settings: BGM (already in `PlayerOptions`, not on the form), swing
  speed, putt speed and ball spin defaults.
- Saved settings in a cookie for every visitor and on the account for signed-in players,
  with a place on `/me` to edit the account's.
- Fitting saved settings to a seed's club rules, and a collapsed summary of the settings
  on the seed page.

Out of scope: seeds that constrain anything other than clubs, recording the new settings
in `entries`, and a bag enforced from PRG ROM (the devplan's "Bag from ROM" polish item).

## Terms

- **Download settings**: everything a player chooses when downloading a seed: name,
  clubs, BGM, swing speed, putt speed, spin. `PlayerOptions`
  (`golf/randomizer/build.py`) is the checked form that finishing consumes.
- **Saved settings**: the download settings remembered for a player, as one versioned
  record. Stored in the cookie and, for a signed-in player, on the account.
- **Fitting**: turning saved settings into what a seed's form starts with, under that
  seed's club rules and finish ABI. Fitting never rejects; it removes what the seed
  forbids and flags what the player must fix.
- **Forced setting**: a setting the seed decides rather than the player. Today only
  clubs can be forced, by a required bag. A setting is also treated as forced when the
  seed's finish ABI cannot write it (see below).

## The settings

The game keeps its option defaults in SRAM from `$6F98`. `InitializeSram` (bank 9) fills
`$6F98-$6FAF` with `$FF` on a new save, and the finisher's `sram_defaults` patch
(`golf/core/patches/sram_defaults.py`) changes what a new save starts with. Values from
the label file:

| Setting | SRAM | Values | New-save value today |
|---|---|---|---|
| BGM | `$6F98` `BGMOnFlag` | `$FF` on, `$00` off | on |
| Swing speed | `$6F99` `SwingSpeedDefault` | `$FF` off, `$00` slow, `$01` medium, `$02` fast | off |
| Putt speed | `$6F9A` `PuttSwingSpeedDefault` | `$FF` off, `$00` slow, `$01` medium, `$02` fast | off |
| Ball spin | `$6F9B` `BallSpinDefault` | `$FF` off, `$00` TOP 2, `$01` TOP 1, `$02` normal, `$03` BACK 1, `$04` BACK 2 | off |

TOP 1 and TOP 2 have no effect on play (`docs/topspin.md`). Whether the form offers them
is an open question below.

Before making the changes to the sram_defaults patch, recommend spending time doing some
reverse-engineering/rom-research to figure out how these SRAM values are *read*.  It
might turn out to be a good time to do the work from converting this from an SRAM-defaults
patch to a "hardcode the values into the rom somewhere" patch.

## Decisions

- **One versioned record.** Saved settings are one small JSON object, `{"v": 1, "name":
  ..., "clubs": [...], "bgm": ..., "swing": ..., "putt": ..., "spin": ...}`. Reading is
  lenient: a missing, unknown or invalid field falls back to that setting's vanilla value,
  never rejecting the whole record. A later setting is a new optional field, not a new
  version or a migration. The record is untrusted input wherever it comes from and is
  validated like a form submission.
- **Cookie for everyone, account for signed-in players.** The cookie keeps guests'
  settings per browser, the same scope as the ROM store. The account keeps a signed-in
  player's settings across browsers. The latest entry is not used as a source of saved
  settings: `entries` holds only name and clubs, and its clubs are the bag a seed's rules
  allowed, not the bag the player prefers.
- **Server-side prefill.** The seed page reads the saved settings and renders the fitted
  form. Fitting is one Python function; `download.js` has no part in it, and the form
  works without it being loaded.
- **Saving is implicit, per setting.** A successful download saves each setting the seed
  did not force. Name, BGM, swing, putt and spin are always saved, unless the seed's ABI
  cannot write them. Clubs are saved only from a seed whose club rules are the defaults
  (`ClubRules()`), so a seed that bans or caps clubs never changes the saved bag.
- **Fitting clubs:** a required bag replaces the saved bag, and the form stays locked as
  it is today. Banned clubs are removed from the saved bag, and the freed slots stay
  empty. A bag over the seed's max is not trimmed by guesswork: the form starts with it,
  flagged, and the player removes clubs. The vanilla default goes through the same
  function, so a seed with a max below 14 and no required bag also flags its starting bag,
  where today it starts over the max and is refused on submit.
- **Collapsed form.** The download form shows a summary of the settings that will be
  written, with the controls in a `<details>` below it, like the seed page's hole table
  and details. The details start open when the fitted form would be refused as it stands
  (a bag over the max), so the player sees what to fix.

## Where the form's starting values come from

Highest first, per setting:

1. This seed's entry, for a signed-in player who has one: name and clubs only.
2. The account's saved settings, for a signed-in player who has them.
3. The cookie's saved settings.
4. The vanilla values: `MARIO`, the vanilla bag, BGM on, the three defaults off.

Every source goes through fitting, so an entry's bag is shown under the seed's current
rules like any other.

## The ROM mechanism and the finish ABI

BGM off is a one-byte edit: the fill loop's `BPL` at `$AD4E` becomes `BNE`, stopping the
loop before `$6F98`. The other three settings need values other than `$FF` and `$00` at
`$6F99-$6F9B`, which the loop cannot produce with a byte edit. The loop is ten bytes
(`$AD46-$AD4F`); loading its fill from a table instead of `#$FF` needs eleven, and the
magic writes at `$AD50` and the name at `$AD5B` follow directly. So the settings need new
code or a table elsewhere in bank 9 or the fixed bank, reached from the loop.

Finish ABI 1 (`docs/patch_stack.md`) promises the finisher only the locations it consumes
today. Finishing into space outside them would write bytes ABI 1 artifacts never promised
to leave vanilla. So this work introduces finish ABI 2:

- The unfinished build installs the new routine with a small table of new-save option
  values at a fixed location, filled with the vanilla values, the way `scorecard_qr`
  installs QR placeholders. The finisher writes the table, expecting the vanilla fill.
  BGM moves into the table, so ABI 2 does not use the `BPL`/`BNE` edit.
- `BUILD_VERSION` and `FINISH_ABI_VERSION` both bump, and the ABI golden in
  `tests/unit/test_build.py` records the new contract.
- The ABI 1 finisher stays, for every seed already stored. It writes name, clubs and BGM
  as now.
- An ABI 1 seed's form omits swing, putt and spin, and saving treats them as forced, so
  downloading an old seed never overwrites them.

The exact routine and its placement are settled in item 1, which may find a better fit.
Anything that keeps ABI 1 artifacts finishable is acceptable.

## Storage

**Cookie.** `golf_download`: the record as compact JSON, base64url-encoded. It is set on
the response to a successful `POST /h/<id>/patch.ips` (the script's `fetch` is
same-origin, so the browser stores it). It is `HttpOnly` and `SameSite=Lax`, `Secure`
when the base URL is HTTPS as the session cookie is, and lasts a year from each download.
It is written for signed-in players too, so signing out on that browser keeps their
settings. A cookie that fails to decode is ignored and overwritten on the next download.

**Account.** A migration appends a table:

```sql
CREATE TABLE download_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users (id),
    settings TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

`server/download_settings.py` is the only code that writes it. A signed-in download
upserts the row by the saving rule; `/me` edits it directly. A signed-in player with no
row gets the cookie's settings, and their first download creates the row.

## The page

- **Seed page.** The download article leads with a summary line of the fitted settings:
  name, the number of clubs, and BGM, swing, putt and spin. A marker is added when the bag
  was adjusted for this seed's rules (clubs removed, or over the max). Below it, a
  `<details>` holds the name field, the club grid and the four option controls as
  `<select>`s or radio groups. It is open when the bag is over the max. All text comes
  from new `seed.download.*` keys with empty `text`.
- **`/me`.** Signed in, a "download settings" section holds the same controls without a
  seed's rules (any bag of up to 14 clubs with the putter), posting to
  `POST /me/download-settings`. The route validates, saves, and redirects back with
  `?result=`, following the admin pages' pattern. Text is new `me.*` keys.

## Development plan

Each item is about one pull request and ends with tests passing. Items 1 and 2 end with
a ROM the user playtests.

1. **ROM research.** Confirm in Mesen what each value of the three defaults does in play,
   including what "off" means for each. Choose the routine and table placement for ABI 2
   with `golf-rom-peek`, checking that nothing in the unfinished stack uses the space.
   Add labels for anything named on the way (following
   `nes-open-golf-label-conventions`). Record the findings in the `sram_defaults.py`
   docstring, and resolve the TOP 1/TOP 2 and "off" open questions with the user.
2. **Patch and finish ABI 2.** The build-time routine and table (written with
   `golf/core/asm6502.py`) and a finisher step that fills the table.
   `PlayerOptions` gains `swing`, `putt` and `spin`, each defaulting to off. Register any
   new patch in `golf/core/patches/registry.py` so `golf-patch` recipes can use it. Bump
   `BUILD_VERSION` and `FINISH_ABI_VERSION`, keep `_finish_abi_1`, and add `_finish_abi_2`.
   Draft an ADR (`golf-adr`, proposed, `--drafted-by Claude`) for ABI 2 and how old seeds
   are finished. Tests: unit tests for the patch bytes; the ABI golden for ABI 2 beside
   ABI 1's; `tests/integration/test_build_rom.py` finishing both ABIs, and a simulator or
   SRAM check that a new save holds the chosen values. Update `docs/patch_stack.md`'s
   list of what the ABI covers, and `docs/manifest.md` if its example shows the ABI.
3. **Saved settings and fitting.** In `server/forms.py`: the saved-settings record with
   lenient `from_json` and `to_json`; `fit(saved, rules, abi)` returning the form's
   starting state, plus which clubs were removed and whether the bag is over the max; and
   `to_save(submitted, rules, abi)` applying the saving rule. `DownloadState.default`
   becomes fitting the vanilla record. Unit tests cover every club-rule case (required
   bag, banned, over max, defaults), a record with unknown, missing and invalid fields,
   and the saving rule for a restricted seed and an ABI 1 seed.
4. **Download form.** `DownloadState` and `player_options_from_state` gain the four
   options. The `seed.html` form gets the summary and the `<details>` with the new
   controls, omitted for ABI 1 seeds. `DownloadView` carries the fitted state, the
   adjusted-bag marker and the open flag. Add `seed.download.*` keys with notes and empty
   text, and any `site.css` rules. Capture the seed page with `golf-site-screenshot
   --generate --expand` and check it at both widths and in both themes. Tests: form
   parsing and refusals for the new fields in `tests/unit/test_server_app.py`, and the
   strings test.
5. **Cookie.** The seed page reads `golf_download` and prefills from it, below an entry for
   this seed. A successful download sets it from `to_save`. Tests: a download sets the
   cookie; a later seed page starts from it; a restricted seed's download keeps the saved
   bag; a garbage cookie is ignored; `tests/integration/test_site_download.py` checks the
   round trip in a browser. Add the cookie to `server/CLAUDE.md` beside the session cookie,
   and to the devplan's "Users and access" section.
6. **Account settings.** A migration adding `download_settings`,
   `server/download_settings.py`, the precedence above for signed-in players, the upsert
   on download, and the `/me` section with `POST /me/download-settings`. Tests in
   `tests/unit/test_server_app.py` and a database test for the module. Update the
   devplan's data model table and routes table, and `server/CLAUDE.md`'s Database section
   with the module's ownership. Draft an ADR for storing saved settings in the cookie and
   on the account, recording that entries were considered and rejected as a source.

## Not Claude's to write

- Every new `seed.download.*` and `me.*` string's `text`.
- `server/content/pages/privacy-policy.md`, which lists the site's cookies and local
  storage. The `golf_download` cookie needs a line there before release.

## Open questions

- **TOP 1 and TOP 2.** Offer them as spin defaults though they play as normal spin, leave
  them out, or offer them with a note?
- **"Off" for each default.** What the game does with `$FF` for swing, putt and spin, and
  whether "off" is worth offering or should be shown as the vanilla behavior. Item 1
  answers the first part.
- **An entry with a recorded round.** `upsert_entry` does not update such an entry, but
  the finisher still writes the name and bag the form submitted, so the ROM can differ
  from the entry. Should the form lock name and clubs to the entry once a round is
  recorded, as it does for a required bag?
- **Resetting.** Is editing the settings enough, or should `/me` also have a "forget my
  settings" action that removes the row (and a way to clear the cookie)?
