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
- Freezing the bag: in a seed with club rules, CHOOSE CLUBS leaves the club house, so the
  bag a ROM plays with is the one chosen on the download form.

Out of scope: seeds that constrain anything other than clubs, and recording the new
settings in `entries`.

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

TOP 1 and TOP 2 have no effect on play (`docs/topspin.md`). The form offers them anyway,
as it offers every value the game accepts.

### How the game uses them

These are the settings on the club house's Options screen (bank 11, reached by the far
call at `$851A` to `$8B1B`). That screen reads and writes all four in SRAM: BGM at
`$8BCE`/`$8BF2`, swing and putt by stepping them with `DEC`/`INC` (`$8C56`-`$8C92`,
`$8CF6`-`$8D32`), and spin from a six-entry grid at `$8FEF` (`FF 00 01 / 02 04 03`,
indexed by `$0728 * 3 + $0727` at `$8E3A`). That grid includes off, TOP 2 and TOP 1, so
the game itself offers all six spin values.

Play reads them in two places:

- **BGM**: `StartCourseBgm` (`$DA05`) skips the course music when `BGMOnFlag` is `$00`.
- **Swing, putt, spin**: `ShotSetupSequence` (bank 13, `$8793`-`$87A8`), at the start of
  every shot, copies each default that is not negative (`BMI` skips `$FF`) over the
  current player's setting: `PlayerSwingSpeed` (`$0123,X`), `PlayerPuttSwingSpeed`
  (`$0125,X`) and the committed spin (`$0127,X`). So a default resets that setting on
  every shot, and off (`$FF`) leaves it as the player last chose it. Off is a real choice,
  and it is what vanilla does.

Because the player can change all four on the Options screen and the game keeps the
change in SRAM, the ROM sets where a new save starts and nothing more. Writing the values
into PRG ROM in place of SRAM would mean patching the Options screen as well, for no gain
in space: the new-save table needs four bytes. Clubs are the one setting worth enforcing
from PRG ROM, and that is a separate piece of work (see the open questions).

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
- **An entry does not lock the form.** Once a round is recorded, `upsert_entry` stops
  updating the entry, but the form still accepts any name and bag, and the ROM may
  differ from the entry. Downloading a seed again after submitting a round is rare, and
  the mismatch affects nothing after it.
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

### Placement

The routine goes in bank 9, beside `InitializeSram`, so the loop reaches it with a plain
`JSR` or `JMP`; the fixed bank is too full to spend on this. Bank 9 has no padding (its
one long run, 256 zeros at `$8DD0`, sits inside a table), so the space comes from code the
randomizer can no longer reach:

- **PLAYER STATS, `$B519`-`$BF89`, about 2.6KB.** The club house's PLAYER STATS screen
  (far call from bank 12 `$852B`, code `$84`), which `menu_trim` removes from the club
  house. Static references into the region come only from inside it:
  `StrokePlayStatsDisplay`, the match play and tournament stats displays, `ConvertToBCD`
  and the 32-bit multiply and divide are all called from the screen alone. The
  `wram_expansion` stubs write inside it (`$BA92`, `$BAE4`, `$BAED`, `$BBA2`, `$BBA8`), so
  the new routine avoids those bytes.
- Also out of reach, but smaller or less certain: match play's opponent pick (`$B322`,
  far-called from bank 13 `$8049`), the prize money and wager code around `$B0CC`-`$B2C8`,
  and `DefaultRosterNamesTable` (190 bytes, only for tournaments).

The ten-byte `$FF` loop at `$AD46` becomes `JMP $B519`, the entry of PLAYER STATS. The
28-byte routine there (`NewSaveOptions`, in `golf/core/patches/new_save_options.py`)
fills `$6F98-$6FAF` with `$FF`, copies the four-byte table at `$B531` (BGM, swing, putt,
spin) over `$6F98-$6F9B`, and jumps back to the magic writes at `$AD50`. The patch
requires `menu_trim`'s removal of PLAYER STATS (`PLAYER_STATS_REMOVED`). Item 1 confirms
with a Mesen breakpoint across the region, through a round and every remaining club house
screen, that nothing reaches it. ADR 0007 records the decision.

## Freezing the bag

The bags are in SRAM: `Player1ClubBag` at `$6027` and `Player2ClubBag` at `$6035`, 14
bytes each. SRAM is mapped at `$6000-$7FFF` whatever PRG bank is switched in, so every
reader sees the bag without a bank switch. Static references, which item 1 confirms with
a Mesen write watchpoint on `$6027-$6042`:

- **Writes**: only `InitializeSram` (bank 9 `$AD3D`, `$AD40`), copying
  `DefaultClubBagTable` (`$AE23`), which the finisher fills, into both bags. The CHOOSE
  CLUBS screen must also write the bags, but not with an absolute store the search
  finds; the watchpoint shows where.
- **Reads**: the shot's club panel and `AutoSelectClub` (bank 13 `$8AF8`, `$8B71`,
  `$8B99`), and the CHOOSE CLUBS screen loading each bag (bank 14 `$AEE9`, `$AF4B`).

So the bag is frozen by taking away the one screen that changes it: `menu_trim` gains a
`choose_clubs` parameter (default true, as today), and false drops CHOOSE CLUBS from the
club house, leaving REGISTER NAME, OPTIONS, TRAINING and CLEAR
SAVED DATA. That is the recipe `docs/menu_system.md` gives for a club house entry: the
count at `$8D64` drops to 4, the destination list at `$8B00` becomes `81 83 87 89`, and
the entries below move up a row. CLEAR SAVED DATA runs `InitializeSram` again, which
copies the same bag back from the ROM.

`unfinished_steps` passes `choose_clubs=False` when the seed places any constraint on
clubs, `manifest.course.clubs != ClubRules()`: a required bag, a banned club or a max
below 14. That is the same test the saving rule uses to decide whether a download's bag
is saved. A seed without club rules keeps CHOOSE CLUBS, and its bag stays on the honour
system as it is today, since no bag breaks its rules. The removal is part of the
unfinished build, so it bumps `BUILD_VERSION` but not the finish ABI; seeds already
stored keep CHOOSE CLUBS. Repointing the bank 13 reads at a
table in PRG ROM was the alternative. It would need the table in bank 13 or the fixed
bank, a new location for the finisher to write, and the bank 14 screen changed or
removed anyway.

A save outlives a re-download: every ROM of a seed shares the seed's SRAM magic, so a
save made from an earlier download keeps that download's bag. Freezing guarantees the
bag played in a seed with club rules is one those rules allowed, not that it is the
entry's latest bag.

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
  `<details>` holds the name field, the club grid, a BGM checkbox and a `<select>` each
  for swing, putt and spin, listing every value the game accepts, off included. It is
  open when the bag is over the max. All text comes from new `seed.download.*` keys with
  empty `text`.
- **`/me`.** Signed in, a "download settings" section holds the same controls without a
  seed's rules (any bag of up to 14 clubs with the putter), posting to
  `POST /me/download-settings`. The route validates, saves, and redirects back with
  `?result=`, following the admin pages' pattern. Below the controls, a "forget my
  settings" button posts to `POST /me/download-settings/forget`, which deletes the row,
  expires this browser's `golf_download` cookie and redirects back the same way. Text is
  new `me.*` keys. A guest has no `/me`; their cookie is replaced by their next download,
  or cleared in the browser.

## Development plan

Each item is about one pull request and ends with tests passing. Items 1 and 2 end with
a ROM the user playtests.

1. **ROM research.** Confirm in Mesen the reads described under "How the game uses
   them": a breakpoint on `$6F99-$6F9B` hits only the Options screen and
   `ShotSetupSequence`, and a default resets its setting on the next shot. Choose the
   routine and table placement for ABI 2 with `golf-rom-peek`, checking that nothing in
   the unfinished stack uses the space. Add labels for anything named on the way
   (following `nes-open-golf-label-conventions`): the per-player spin at `$0127`, the
   Options screen at bank 11 `$8B1B` and its spin grid at `$8FEF`. Put a write
   watchpoint on the bags (`$6027-$6042`) through CHOOSE CLUBS, a round, TRAINING and
   each CLEAR SAVED DATA option, and label the CHOOSE CLUBS screen's write. Record the
   findings in the `sram_defaults.py` docstring.
2. **Patch and finish ABI 2.** The build-time routine and table (written with
   `golf/core/asm6502.py`) and a finisher step that fills the table.
   `PlayerOptions` gains `swing`, `putt` and `spin`, each defaulting to off. Register any
   new patch in `golf/core/patches/registry.py` so `golf-patch` recipes can use it. Bump
   `BUILD_VERSION` and `FINISH_ABI_VERSION`, keep `_finish_abi_1`, and add `_finish_abi_2`.
   `menu_trim` gains `choose_clubs`, which `unfinished_steps` sets false for a seed with
   club rules; add it to the recipe parameters in the registry and in
   `docs/patch_stack.md`'s table, update `menu_trim`'s docstring and the worked example
   in `docs/menu_system.md`, replace the "Future option" note in `sram_defaults.py`, and
   update the devplan's honour-system paragraph under entries and its "Bag from ROM"
   polish item.
   Draft an ADR (`golf-adr`, proposed, `--drafted-by Claude`) for ABI 2 and how old seeds
   are finished. Tests: unit tests for the patch bytes; the ABI golden for ABI 2 beside
   ABI 1's; `tests/integration/test_build_rom.py` finishing both ABIs, and a simulator or
   SRAM check that a new save holds the chosen values; `test_menu_trim.py` and
   `test_menu_trim_rom.py` for the four-entry club house, and `test_build.py` for a seed
   with club rules getting it and one without keeping five entries. Update `docs/patch_stack.md`'s
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
   on download, and the `/me` section with `POST /me/download-settings` and
   `POST /me/download-settings/forget`. Tests in
   `tests/unit/test_server_app.py` and a database test for the module. Update the
   devplan's data model table and routes table, and `server/CLAUDE.md`'s Database section
   with the module's ownership. Draft an ADR for storing saved settings in the cookie and
   on the account, recording that entries were considered and rejected as a source.

## Not Claude's to write

- Every new `seed.download.*` and `me.*` string's `text`.
- `server/content/pages/privacy-policy.md`, which lists the site's cookies and local
  storage. The `golf_download` cookie needs a line there before release.

## Open questions

None.
