#!/usr/bin/env python3
"""
NES Open Tournament Golf - Hole Difficulty

The expected strokes a player of a given skill takes to hole out from the tee,
from the game's own physics (`golf.difficulty.solver`). For now with one pin
and no wind.

The first run builds the landing table the solver screens intents with (about
a million shots, some minutes on every core) and caches it under `.cache/`.
The first run on each hole and pin also plays every putt on its green once
(`golf.difficulty.green`, a few minutes) and caches that too.

Examples:
    golf-difficulty nes_open_us.nes --course us --hole 1
    golf-difficulty nes_open_us.nes --course uk --hole 9 --skill 1.5 --grid 8
    golf-difficulty nes_open_us.nes --build-table
"""

import argparse
import json
import math
import time
from pathlib import Path

from golf.core.clubs import Club
from golf.core.rom_reader import RomReader
from golf.difficulty.landing import cache_path, load_or_build
from golf.difficulty.player import Intent, Skill
from golf.difficulty.solver import GREEN, TEE, HoleSolver, Settings
from golf.physics import PhysicsTables

SPEEDS = ("slow", "medium", "fast")
HI_LO = {-1: "low", 0: "", 1: "high"}


def describe(intent: Intent) -> str:
    parts = [
        Club(intent.club).label,
        SPEEDS[intent.swing_speed],
        f"aim {intent.aim}",
        f"power {intent.power_target}",
    ]
    if intent.club != Club.PT:
        if intent.accuracy_target != 0x30:
            parts.append(f"accuracy {intent.accuracy_target - 0x30:+}")
        if intent.hi_lo:
            parts.append(HI_LO[intent.hi_lo])
        parts.append(intent.spin.name.lower().replace("_", " "))
    return ", ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("rom", help="ROM whose physics to use")
    parser.add_argument("--course", default="us", help="directory under courses/")
    parser.add_argument("--hole", type=int, default=1)
    parser.add_argument("--pin", type=int, default=0, choices=range(4))
    parser.add_argument(
        "--skill",
        type=float,
        default=1.0,
        help="standard deviation of every error, in frames and aim steps",
    )
    defaults = Settings()
    parser.add_argument("--grid", type=int, default=defaults.grid)
    parser.add_argument("--shortlist", type=int, default=defaults.shortlist)
    parser.add_argument(
        "--candidates",
        type=int,
        default=defaults.candidates,
        help="groups the screen scores again under the player's errors; 0 for none",
    )
    parser.add_argument("--reach", type=float, default=defaults.reach)
    parser.add_argument(
        "--scatter-on-fairway",
        action="store_true",
        help="play the screen's second pass over plain fairway, not the hole",
    )
    parser.add_argument("--refresh", type=int, default=defaults.refresh)
    parser.add_argument(
        "--race",
        type=int,
        default=defaults.race,
        help="intents kept after playing a shortlist roughly; 0 plays all exactly",
    )
    parser.add_argument("--refresh-reach", type=float, default=defaults.refresh_reach)
    parser.add_argument("--tolerance", type=float, default=defaults.tolerance)
    parser.add_argument("--rounds", type=int, default=defaults.rounds)
    parser.add_argument(
        "--rng-states",
        type=int,
        default=defaults.rng_states,
        help="RNG states each full swing is played from",
    )
    parser.add_argument(
        "--error-points",
        type=int,
        default=defaults.error_points,
        help="about how many errors stand for each draw off the green",
    )
    parser.add_argument("--workers", type=int, help="processes; default every core")
    parser.add_argument(
        "--build-table", action="store_true", help="only build the landing table"
    )
    parser.add_argument("--output", type=Path, help="write every state's value as JSON")
    args = parser.parse_args()

    tables = PhysicsTables.from_rom(RomReader(args.rom))
    if args.build_table or not cache_path(tables).exists():
        started = time.perf_counter()
        load_or_build(tables, args.workers)
        print(f"landing table built in {time.perf_counter() - started:.0f} s")
        if args.build_table:
            return

    settings = Settings(
        grid=args.grid,
        shortlist=args.shortlist,
        candidates=args.candidates,
        scatter_on_hole=not args.scatter_on_fairway,
        reach=args.reach,
        refresh=args.refresh,
        race=args.race,
        refresh_reach=args.refresh_reach,
        tolerance=args.tolerance,
        rounds=args.rounds,
        rng_states=args.rng_states,
        error_points=args.error_points,
    )
    solver_args = {"workers": args.workers} if args.workers else {}
    solver = HoleSolver(
        args.rom,
        Path("courses") / args.course / f"hole_{args.hole:02}.json",
        pin=args.pin,
        skill=Skill.scaled(args.skill),
        settings=settings,
        **solver_args,
    )
    started = time.perf_counter()
    solution = solver.solve()
    par = solver.hole.metadata["par"]
    print(
        f"\n{args.course} hole {args.hole} (par {par}), pin {args.pin}, "
        f"skill {args.skill}: {solution.tee:.3f} strokes from the tee"
    )
    print(f"  from the tee: {describe(solution.policy[TEE])}")
    print(
        f"  {len(solution.policy)} states valued, {solution.shots} intents played, "
        f"{solution.rounds} rounds, {time.perf_counter() - started:.0f} s"
    )
    print(f"  visits to spots too rare to value: {solution.unvalued:.4f} a hole")

    played = {
        key: sorted(
            (
                {
                    "intent": describe(t.intent),
                    "rank": t.rank,
                    "screened": t.screened,
                    "expected": q,
                }
                for t, q in zip(transitions, solver.q(transitions), strict=True)
            ),
            key=lambda p: p["expected"],
        )
        for key, transitions in solution.transitions.items()
    }
    print_ranks(solution.visits, played)

    if args.output:
        states = [
            {
                "class": key[0],
                "x": solution.positions[key].x,
                "y": solution.positions[key].y,
                "expected": solution.expected[key],
                "visits": solution.visits.get(key, 0.0),
                "intent": describe(solution.policy[key]),
                "played": played[key],
            }
            for key in solution.policy
        ]
        args.output.write_text(json.dumps({"tee": solution.tee, "states": states}))


def print_ranks(visits: dict, played: dict) -> None:
    """
    How well the screen ranked the intents the solver chose off the green,
    weighted by visits (the green is solved whole, with no screen).
    """
    visits = {key: mass for key, mass in visits.items() if key[0] != GREEN}
    total = sum(visits.values())
    if not total:
        return
    limits = {"1st": 1, "2nd-4th": 4, "5th-8th": 8, "9th+": math.inf}
    buckets = dict.fromkeys(limits, 0.0)
    for key, mass in visits.items():
        rank = played[key][0]["rank"]
        buckets[next(name for name, limit in limits.items() if rank < limit)] += mass
    shares = ", ".join(f"{name} {mass / total:.0%}" for name, mass in buckets.items())
    print(f"  the screen ranked the chosen intent (by visits): {shares}")


if __name__ == "__main__":
    main()
