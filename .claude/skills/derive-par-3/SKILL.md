---
name: derive-par-3
description: >
  Making a derived par 3 from a vanilla par 4 or par 5's forward tee, with jdharms
  doing the editor work and Claude running the commands: copying the base to
  courses/scratch/, mapping where a tee can go by yardage, checking the edited hole
  against its base, measuring its distance from the pins, and the golf-derive dry run,
  publish and check. Use whenever jdharms wants to make, check, publish or correct a
  forward-tee par 3, or asks which tee spots a hole offers.
---

# Deriving a par 3 from a forward tee

jdharms edits the hole in `golf-editor`; you copy, map, check, measure and publish. The
format and the command are in `docs/derived_holes.md`; why these holes are drawn only in
par 3 and executive courses is ADR 0028. Commits are jdharms's to write.

The helper below runs from the repo root and needs the vanilla holes rehydrated
(`golf-rehydrate`) and `nes_open_us.nes` present:

```bash
H=".claude/skills/derive-par-3/scripts/forward_tee.py"
uv run python $H start nes_uk/18                  # copy into courses/scratch/, then map
uv run python $H map courses/scratch/nes_uk_18_forward3.json
uv run python $H inspect courses/scratch/nes_uk_18_forward3.json nes_uk/18 --set-distance
uv run python $H compare courses/scratch/nes_uk_18_forward3.json nes_uk/18
```

## The steps

1. **Start.** `start <base>` copies the base hole to
   `courses/scratch/<base>_forward3.json` (git ignores `courses/`) and prints the map:
   every open lie (fairway, tee, light rough) lettered by yards to the middle of the
   four pins, `a` 110-150, `b` 150-200, `c` 200-250, `1` under 110, and the hazards
   (`~` water, `s` sand, `#` forest or out of bounds, `T` tree trunk, `:` deep rough,
   `G` green). Summarize the spots in each band by tile row and column (pixel / 8), and
   say whether each crosses a hazard to the green. Always end with the exact command to
   open the copy, with the real file name filled in, ready to paste:
   `uv run golf-editor courses/scratch/<base>_forward3.json`.
2. **jdharms edits** in `uv run golf-editor <file>`:
   - a tee box stamped with the stamp tool (K, `teebox/`), forest carved first if needed;
   - the tee moved onto it with the position tool (R, arrow keys);
   - rows cropped from the bottom with `-`, two at a time down to 30, which also sets
     `scroll_limit`. The green is near the top, so a bottom crop keeps what matters;
     the map marks row 29, the last row a 30-row crop keeps;
   - par set to 3 in the metadata dialog (D). The distance is left for you.
3. **Inspect.** `inspect <file> <base>` reports the four pin distances and their mean,
   the cells changed against the base, the tee box against vanilla's (shape, the tee's
   offset from the box's corner, palette 1) and the bottom row. Flag anything that is
   not a tee box, a carve or a crop, and a tee box unlike vanilla's. `--set-distance`
   writes the mean into the file: the base's metadata distance means nothing for the
   new hole, and vanilla's own are off by a few yards.

   Then `compare <file> <base>`, and Read the PNG it writes beside the hole file
   (`courses/scratch/<base>_forward3.png`): the base at left, the edit at right, 4x,
   the pins as numbered red dots, and a line from the tee to the middle of the pins
   ticked every 25 yards (2 yards to a pixel). Look at it to judge the tee box and the
   fairway around it, then give jdharms the path and walk the line: where the fairway
   ends and each hazard starts and stops in yards, and which pins bring a hazard
   most into play. The same image serves as the before/after for community sign-off.
4. **Dry run.** Show jdharms the report:
   ```bash
   uv run golf-derive new <base> <file> community/<base_with_underscores>_forward3 \
     --author jdharms --dry-run
   ```
   It checks the hole could be built, takes the delta, rebuilds the hole from it, runs
   every transform, and warns over 35% of the shared terrain rewritten (refuses over 60%
   without `--allow-large`). A tee box and a crop is a few cells and about 1%.
5. **Publish** only after the community has signed off on the hole, and when jdharms
   says to. Until then the edited file stays in `courses/scratch/` and the catalog is
   untouched: once committed, an id can never be removed from the index
   (`tests/meta/test_catalog_ids.py`). Publishing is the same command without `--dry-run`. It writes
   the delta under `data/catalog/derived/community/`, the entry (bumping the index
   version, once per publish, which is harmless) and the curation record, putting the
   base in a family named after it if it had none and tagging the new hole `short`.
6. **Check:** `uv run golf-derive check`, then `uv run pytest`. The tests count derived
   holes from the catalog (`tests/catalog_counts.py`) and pin their golden courses, so a
   new hole should break nothing; if one does, read it before changing it.

## What jdharms has settled

- **The bottom edge stays hard.** A crop that cuts across fairway is a nod to the rest
  of the hole being out of sight; don't offer to tidy it.
- **Handicaps don't matter** for now; the base's carries over. They will come from
  production stats later.
- **Lineages** are `community/<base>_forward3`, author `jdharms`. A second par 3 from
  the same base (two tee spots on one hole) needs a slug of its own; ask jdharms what.
- **jdharms picks the tee spot.** For a par 4, the spot is usually where the drive
  lands: the approach the par 4 yields, not a tee moved up the line. Offer the map's
  options and how each plays; don't choose.
- **Trees between tee and green** are cleared by the ball's arc unless the tee is close
  behind them; only trees just in front of the tee block a shot.

## Where the mix stands

Of the vanilla par 3s' 23 distinct designs, none averages under 150 yards, 180-189 is
empty, and 190-230 is crowded; 12 are forced carries, mostly water. Short holes, holes
whose hazard depends on the pin, and sand carries add the most. When jdharms is choosing
a distance, say where it lands against that.

jdharms keeps candidate notes in `docs/planning/short_holes.md`, a scratch file: read it
for their intent, but don't edit it or cite it from other docs or records.

## Correcting a published hole

A change that matters to play is a new version: `uv run golf-derive export <id> -o
<file>`, edit, then `new` with the same lineage, which publishes `@2`. A delta may be
corrected in place only when play is unchanged (`docs/catalog.md`). Every version of a
lineage keeps its first par.
