"""Helpers for making a par 3 from a vanilla hole's forward tee.

    start <base>                 copy the base into courses/scratch/ and map it
    map <hole.json>              the playable ground, lettered by yards to the pins
    inspect <hole.json> <base>   an edited hole against its base; --set-distance
                                 writes the measured distance into the file
    compare <hole.json> <base>   the base and the edited hole side by side, with a
                                 line from the tee to the middle of the pins ticked
                                 every 25 yards; -o for the PNG (default: beside
                                 the hole file)

Run from the repo root: uv run python .claude/skills/derive-par-3/scripts/forward_tee.py
"""

import argparse
import json
import math
import shutil
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics.state import Lie
from golf.physics.terrain import HoleGround, TerrainTables
from golf.randomizer.catalog import REPO_ROOT, Catalog, HoleStore
from golf.rendering.rangefinder import HoleRenderer

SCRATCH = REPO_ROOT / "courses" / "scratch"
US_ROM_PATH = REPO_ROOT / "nes_open_us.nes"
NES_COURSES = ("us", "uk", "japan")
TEE_TILES = range(0x35, 0x3D)
#: yard bands for the map: under 110 is "1", then a, b, c up to 250
BANDS = ((110, "1"), (150, "a"), (200, "b"), (250, "c"))
SYMBOLS = {
    "deep": ":",
    "sand": "s",
    "water": "~",
    "oob": "#",
    "tree": "T",
    "green": "G",
}


def tables() -> TerrainTables:
    """The fixed bank's terrain tables. Mario Open holds the same masks, so these read
    its holes too. The bottom limit is lifted so holes of any height classify; the map
    stops at the hole's own height instead."""
    read = TerrainTables.from_rom(RomReader(str(US_ROM_PATH)))
    return replace(read, terrain_rows=60, bottom_y=(0xFFFF,) * len(read.bottom_y))


def kind(ground: HoleGround, x: int, y: int) -> str:
    if not 0 <= x < 176 or y < 0:
        return "oob"
    t = ground.classify(x, 0, y, 0)
    if t.tree_trunk:
        return "tree"
    return {
        Lie.GREEN: "green",
        Lie.BUNKER: "sand",
        Lie.WATER: "water",
        Lie.OUT_OF_BOUNDS: "oob",
    }.get(t.lie, "deep" if t.lie == Lie.ROUGH and t.rough_depth else "open")


def pins(raw: dict) -> list[tuple[float, float]]:
    """The four flags in pixels, as `InitHole` places them (golf/physics/shot.py)."""
    gx, gy = raw["green"]["x"], raw["green"]["y"]

    def place(green: int, offset: int) -> float:
        return green + (offset >> 3) + ((offset & 7) * 32 + 0x28) / 256

    return [
        (place(gx, f["x_offset"]), place(gy, f["y_offset"]))
        for f in raw["flag_positions"]
    ]


def yards(a: tuple[float, float], b: tuple[float, float]) -> float:
    return 2 * math.hypot(a[0] - b[0], a[1] - b[1])


def base_path(base: str) -> Path:
    catalog, store = Catalog.load(), HoleStore()
    entry = catalog[base]
    if entry.kind != "vanilla":
        sys.exit(f"{base} is not a vanilla hole")
    return store.path_for(entry)


def draw_map(path: Path) -> None:
    raw = json.loads(path.read_text())
    hole = HoleData.from_dict(raw)
    ground = HoleGround(hole, tables())
    flags = pins(raw)
    middle = (sum(p[0] for p in flags) / 4, sum(p[1] for p in flags) / 4)
    print(
        f"{path.name}: par {raw['par']}, {raw['distance']}y, "
        f"{hole.terrain_height} rows, green {raw['green']}, tee {raw['tee']}"
    )
    print(
        "open ground by yards to the middle of the pins: "
        "1 <110, a 110-150, b 150-200, c 200-250, . beyond"
    )
    # Two characters to a tile column: label each column at its first character.
    print("col tens "[:9] + "".join(f"{c // 10 or ' '} " for c in range(22)))
    print("col      " + "".join(f"{c % 10} " for c in range(22)))
    top = max(0, hole.green_y - 24) // 8 * 8
    for y in range(top, hole.terrain_height * 8, 4):
        row = ""
        for x in range(0, 176, 4):
            k = kind(ground, x, y)
            if k == "open":
                d = yards((x, y), middle)
                row += next((s for limit, s in BANDS if d < limit), ".")
            else:
                row += SYMBOLS[k]
        marker = "  <- row 29, the last of a 30-row crop" if y // 8 == 29 else ""
        print(f"y{y:4} r{y // 8:2}  {row}{marker if y % 8 == 4 else ''}")


def vanilla_tee_boxes() -> tuple[Counter, Counter]:
    """Tee box tile shapes and the tee's offset from the box's corner, over NES Open."""
    shapes, offsets = Counter(), Counter()
    for course in NES_COURSES:
        for p in sorted((REPO_ROOT / "courses" / course).glob("hole_*.json")):
            h = json.loads(p.read_text())
            rows = [r.split() for r in h["terrain"]["rows"]]
            cells = [
                (r, c)
                for r in range(h["terrain"]["height"])
                for c in range(22)
                if int(rows[r][c], 16) in TEE_TILES
            ]
            r0, c0 = min(r for r, _ in cells), min(c for _, c in cells)
            r1, c1 = max(r for r, _ in cells), max(c for _, c in cells)
            shapes[
                tuple(" ".join(rows[r][c0 : c1 + 1]) for r in range(r0, r1 + 1))
            ] += 1
            offsets[(h["tee"]["x"] - c0 * 8, h["tee"]["y"] - r0 * 8)] += 1
    return shapes, offsets


def inspect(path: Path, base: str, set_distance: bool) -> None:
    raw = json.loads(path.read_text())
    original = json.loads(base_path(base).read_text())
    height = raw["terrain"]["height"]
    tee = (raw["tee"]["x"], raw["tee"]["y"])
    each = [yards(tee, p) for p in pins(raw)]
    mean = round(sum(each) / 4)
    print(f"par {raw['par']}, distance in file {raw['distance']}")
    print(f"tee {tee}, tile column {tee[0] // 8}, row {tee[1] // 8}")
    print(f"pins {[round(d) for d in each]} yards, mean {mean}")
    print(
        f"rows {height}, scroll_limit {raw['scroll_limit']} "
        f"(wants {(height - 28) // 2})"
    )

    new_rows = [r.split() for r in raw["terrain"]["rows"]]
    old_rows = [r.split() for r in original["terrain"]["rows"]]
    changed = [
        (r, c, old_rows[r][c], new_rows[r][c])
        for r in range(min(height, len(old_rows)))
        for c in range(22)
        if old_rows[r][c] != new_rows[r][c]
    ]
    print(f"terrain cells changed in the visible rows: {len(changed)}")
    for r, c, old, new in changed[:40]:
        print(f"  row {r} column {c}: {old} -> {new}")
    attrs = [
        (r, c)
        for r in range(height // 2)
        for c in range(11)
        if raw["attributes"]["rows"][r][c] != original["attributes"]["rows"][r][c]
    ]
    print(f"palettes changed: {len(attrs)}")
    print(
        f"greens unchanged: {raw['greens'] == original['greens']}, "
        f"pins unchanged: {raw['flag_positions'] == original['flag_positions']}, "
        f"green unchanged: {raw['green'] == original['green']}"
    )

    boxes = [
        (r, c)
        for r in range(height)
        for c in range(22)
        if int(new_rows[r][c], 16) in TEE_TILES
    ]
    if not boxes:
        print("no tee box tiles in the visible rows")
    else:
        r0, c0 = min(r for r, _ in boxes), min(c for _, c in boxes)
        r1, c1 = max(r for r, _ in boxes), max(c for _, c in boxes)
        shape = tuple(" ".join(new_rows[r][c0 : c1 + 1]) for r in range(r0, r1 + 1))
        offset = (tee[0] - c0 * 8, tee[1] - r0 * 8)
        palettes = sorted({raw["attributes"]["rows"][r // 2][c // 2] for r, c in boxes})
        shapes, offsets = vanilla_tee_boxes()
        print(
            f"tee box {shape}: {shapes.get(shape, 0)} vanilla holes use it; "
            f"tee offset {offset}: {offsets.get(offset, 0)} vanilla holes; "
            f"palettes {palettes} (vanilla uses 1)"
        )
    print(f"bottom row {height - 1}: {' '.join(new_rows[height - 1])}")

    if set_distance:
        raw["distance"] = mean
        path.write_text(json.dumps(raw, indent=2) + "\n")
        print(f"wrote distance {mean}")


#: the comparison's zoom, the gap between its two holes and its tick spacing
SCALE, GAP, TICK_YARDS = 4, 32, 25


def compare(path: Path, base: str, out: Path | None) -> None:
    raw = json.loads(path.read_text())
    original = json.loads(base_path(base).read_text())
    renderer = HoleRenderer()

    def render(hole: dict) -> Image.Image:
        img = renderer.main(hole, 0).convert("RGB")
        return img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)

    before, after = render(original), render(raw)
    draw = ImageDraw.Draw(after)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:  # Pillow before 10.1
        font = ImageFont.load_default()

    flags = pins(raw)
    tee = (raw["tee"]["x"], raw["tee"]["y"])
    for i, (x, y) in enumerate(flags, 1):
        x, y = x * SCALE, y * SCALE
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill="red")
        draw.text((x + 5, y - 8), str(i), fill="white", font=font)
    middle = (sum(p[0] for p in flags) / 4, sum(p[1] for p in flags) / 4)
    draw.line([*(v * SCALE for v in tee), *(v * SCALE for v in middle)], "white", 2)
    length = math.hypot(middle[0] - tee[0], middle[1] - tee[1])
    ux, uy = (middle[0] - tee[0]) / length, (middle[1] - tee[1]) / length
    for yd in range(TICK_YARDS, round(yards(tee, middle)), TICK_YARDS):
        x = (tee[0] + ux * yd / 2) * SCALE  # yards() is 2 yards a pixel
        y = (tee[1] + uy * yd / 2) * SCALE
        draw.line([x + uy * 8, y - ux * 8, x - uy * 8, y + ux * 8], "white", 2)
        draw.text((x - uy * 14 - 8, y + ux * 14 - 8), str(yd), fill="yellow", font=font)

    sheet = Image.new(
        "RGB",
        (before.width + GAP + after.width, max(before.height, after.height)),
        "white",
    )
    sheet.paste(before, (0, 0))
    sheet.paste(after, (before.width + GAP, 0))
    # Comparisons collect in a folder per vanilla course beside the hole file.
    out = out or path.parent / base.split("/")[0] / path.with_suffix(".png").name
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    each = [round(yards(tee, p)) for p in flags]
    print(f"wrote {out}: {base} left, the edit right; pins 1-4 at {each} yards")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("base", help="a vanilla hole id, e.g. nes_us/02")
    show = sub.add_parser("map")
    show.add_argument("hole", type=Path)
    check = sub.add_parser("inspect")
    check.add_argument("hole", type=Path)
    check.add_argument("base")
    check.add_argument("--set-distance", action="store_true")
    side = sub.add_parser("compare")
    side.add_argument("hole", type=Path)
    side.add_argument("base")
    side.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    if args.command == "start":
        target = SCRATCH / f"{args.base.replace('/', '_')}_forward3.json"
        if target.exists():
            sys.exit(f"{target} exists; map it or remove it first")
        SCRATCH.mkdir(parents=True, exist_ok=True)
        shutil.copy(base_path(args.base), target)
        print(f"copied to {target.relative_to(REPO_ROOT)}")
        draw_map(target)
    elif args.command == "map":
        draw_map(args.hole)
    elif args.command == "compare":
        compare(args.hole, args.base, args.output)
    else:
        inspect(args.hole, args.base, args.set_distance)


if __name__ == "__main__":
    main()
