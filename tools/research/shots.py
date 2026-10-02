#!/usr/bin/env python3
"""
NES Open Tournament Golf - Shot Table

Plays shots through the `golf.physics` model of the game's ball physics and
prints how far they go: carry and total for every club at every swing speed,
or the detail of one club's shot.

Distances are in the game's yards (two per pixel). The ground is uniform, so
there are no trees, slopes or lie changes along the way; the shot is launched
from --launch-lie and lands and rolls on --ground.

Examples:
    golf-shots nes_open_us.nes
    golf-shots nes_open_us.nes --power 8 --hi-lo high
    golf-shots nes_open_us.nes --wind 0 9 --ground rough --rough-depth 1
    golf-shots nes_open_us.nes --club 7I --speed fast --path
"""

import argparse

from golf.core.patches.sram_defaults import Club, parse_club
from golf.core.rom_reader import RomReader
from golf.physics import (
    Lie,
    PhysicsTables,
    ShotInput,
    Spin,
    Terrain,
    UniformGround,
    simulate,
)

SPEEDS = {"slow": 0, "medium": 1, "fast": 2}
HI_LO = {"low": -1, "normal": 0, "high": 1}
LIES = {lie.name.lower().replace("_", "-"): lie for lie in Lie}
SPINS = {spin.name.lower().replace("_", ""): spin for spin in Spin}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("rom", help="ROM whose physics tables to use")
    parser.add_argument(
        "--power",
        type=int,
        default=0,
        help="power-meter stop, 0 (full) to 48 (none); default 0",
    )
    parser.add_argument(
        "--accuracy",
        type=int,
        default=0x30,
        help="accuracy-meter stop, 48 is dead center; default 48",
    )
    parser.add_argument("--hi-lo", choices=HI_LO, default="normal")
    parser.add_argument("--spin", choices=SPINS, default="normal")
    parser.add_argument(
        "--wind",
        nargs=2,
        type=int,
        metavar=("DIRECTION", "SPEED"),
        default=(0, 0),
        help="WindDirection (0-255, 0 blows up the screen) and WindSpeed",
    )
    parser.add_argument("--aim", type=int, default=0, help="Aiming, 0-255; default 0")
    parser.add_argument("--launch-lie", choices=LIES, default="tee")
    parser.add_argument("--ground", choices=LIES, default="fairway")
    parser.add_argument("--rough-depth", type=int, choices=(0, 1), default=0)
    parser.add_argument(
        "--rng", type=lambda s: int(s, 0), default=0x1234, help="starting RngState"
    )
    parser.add_argument(
        "--club", type=parse_club, help="one club (1W, 7I, PW...) instead of the table"
    )
    parser.add_argument("--speed", choices=SPEEDS, default="medium")
    parser.add_argument(
        "--path", action="store_true", help="with --club: print every 10th frame"
    )
    args = parser.parse_args()

    tables = PhysicsTables.from_rom(RomReader(args.rom))
    ground = UniformGround(Terrain(LIES[args.ground], rough_depth=args.rough_depth))
    launch = Terrain(LIES[args.launch_lie], rough_depth=args.rough_depth)

    def shot(club: Club, speed: int) -> ShotInput:
        return ShotInput(
            club=club,
            swing_speed=speed,
            power_stop=args.power,
            accuracy_stop=args.accuracy,
            hi_lo=HI_LO[args.hi_lo],
            spin=SPINS[args.spin],
            aim=args.aim,
            wind_direction=args.wind[0],
            wind_speed=args.wind[1],
            rng_state=args.rng,
        )

    if args.club:
        club = args.club
        result = simulate(
            shot(club, SPEEDS[args.speed]), ground, tables, launch, record_path=True
        )
        print(f"{club.label} {args.speed}")
        print(
            f"  carry    {result.carry_yards:6.1f} yd  (frame {result.landing_frame})"
        )
        print(f"  roll     {result.roll_yards:6.1f} yd")
        print(f"  total    {result.total_yards:6.1f} yd  (frame {result.ball.frames})")
        print(f"  offline  {result.offline_yards:+6.1f} yd")
        print(f"  apex     {result.apex:6.1f} px of sprite lift")
        print(f"  rests on {result.ball.lie.name.lower()}")
        if args.path:
            print("\n  frame      x       y  height")
            for frame, point in enumerate(result.path, start=1):
                if frame % 10 == 0 or frame == len(result.path):
                    print(
                        f"  {frame:5} {point.x:6.1f} {point.y:7.1f} {point.height:6.1f}"
                    )
        return

    print("carry / total, yards")
    print(f"{'club':<5}" + "".join(f"{name:>14}" for name in SPEEDS))
    for club in Club:
        cells = []
        for speed in SPEEDS.values():
            result = simulate(shot(club, speed), ground, tables, launch)
            cells.append(f"{result.carry_yards:.0f} / {result.total_yards:.0f}")
        print(f"{club.label:<5}" + "".join(f"{cell:>14}" for cell in cells))


if __name__ == "__main__":
    main()
