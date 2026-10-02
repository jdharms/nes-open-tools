"""
The solves `golf-difficulty` writes, gathered: one row per hole, a slim archive of the
solves for keeping, and the Markdown tables `docs/hole_difficulty.md` shows.

A solves directory holds one directory of `hole_NN.json` per course, named as the
catalog names the course (`nes_us`, `jp_uk`), and any `.log` files beside them.
"""

import io
import json
import statistics
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

#: Course directories in the order the tables list them, with their names there.
COURSES = {
    "nes_japan": "NES Japan",
    "nes_us": "NES US",
    "nes_uk": "NES U.K.",
    "jp_japan": "Mario Japan",
    "jp_australia": "Mario Australia",
    "jp_france": "Mario France",
    "jp_hawaii": "Mario Hawaii",
    "jp_uk": "Mario U.K.",
}

#: What the archive keeps of each state: the play, not every intent tried.
SLIM_STATE = ("class", "x", "y", "expected", "visits", "intent")


@dataclass(frozen=True)
class HoleResult:
    lineage: str
    """`nes_us/16`, as the catalog and curation name the hole."""
    course: str
    hole: int
    par: int
    yards: int
    handicap: int
    expected: float
    """Expected strokes from the tee."""
    unvalued: float | None
    """Visits a hole to spots too rare to value; None in solves written before it was kept."""
    rounds: int | None
    skill: float | None
    pin: int | None

    @property
    def over_par(self) -> float:
        return self.expected - self.par

    @property
    def mario(self) -> bool:
        return self.course.startswith("jp_")


def course_json(courses_root: Path, course: str, hole: int) -> Path:
    """Where a course directory's hole lives under `courses/`."""
    folder = f"jp/{course}" if course.startswith("jp_") else course.removeprefix("nes_")
    return courses_root / folder / f"hole_{hole:02}.json"


def load(solves: Path, courses_root: Path = Path("courses")) -> list[HoleResult]:
    """Every solved hole under `solves`, in table order."""
    results = []
    for course in COURSES:
        for path in sorted((solves / course).glob("hole_*.json")):
            solve = json.loads(path.read_text())
            hole = int(path.stem.removeprefix("hole_"))
            meta = json.loads(course_json(courses_root, course, hole).read_text())
            results.append(
                HoleResult(
                    lineage=f"{course}/{hole:02}",
                    course=course,
                    hole=hole,
                    par=int(solve["par"]),
                    yards=int(meta["distance"]),
                    handicap=int(meta["handicap"]),
                    expected=float(solve["tee"]),
                    unvalued=solve.get("unvalued"),
                    rounds=solve.get("rounds"),
                    skill=solve.get("skill"),
                    pin=solve.get("pin_index"),
                )
            )
    return results


def summary(results: Iterable[HoleResult]) -> dict:
    """One row per hole, for `data/difficulty/holes.json`."""
    holes = []
    for result in results:
        row = asdict(result)
        row["over_par"] = round(result.over_par, 4)
        row["expected"] = round(result.expected, 4)
        holes.append(row)
    return {"wind": None, "holes": holes}


def slim(solve: dict) -> dict:
    """A solve without the intents its states played but did not choose."""
    kept = {key: value for key, value in solve.items() if key != "states"}
    kept["states"] = [
        {key: state[key] for key in SLIM_STATE} for state in solve["states"]
    ]
    return kept


def write_archive(solves: Path, archive: Path) -> int:
    """
    Every course's solves, slimmed, and the logs beside them, as a .tar.xz.
    Entries are sorted and undated, so the same solves give the same archive.
    How many files it holds.
    """
    entries: list[tuple[str, bytes]] = []
    for course in COURSES:
        for path in sorted((solves / course).glob("hole_*.json")):
            data = json.dumps(slim(json.loads(path.read_text())), sort_keys=True)
            entries.append((f"{course}/{path.name}", data.encode()))
    for path in sorted(solves.glob("*.log")):
        entries.append((path.name, path.read_bytes()))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:xz", preset=9) as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return len(entries)


# --- tables --------------------------------------------------------------------


def _table(header: list[str], rows: Iterable[Iterable[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _spearman(a: list[float], b: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2
            i = j + 1
        return out

    return statistics.correlation(ranks(a), ranks(b))


def course_table(results: list[HoleResult]) -> str:
    """Each course's round, out and in, by par, and against the game's handicaps."""
    rows = []
    for course, name in COURSES.items():
        holes = [r for r in results if r.course == course]
        if not holes:
            continue
        total = sum(r.expected for r in holes)
        out = sum(r.expected for r in holes if r.hole <= 9)
        by_par = []
        for par in (3, 4, 5):
            over = [r.over_par for r in holes if r.par == par]
            by_par.append(f"{statistics.mean(over):+.2f}" if over else "")
        complete = len(holes) == 18
        rows.append(
            [
                name,
                f"{out:.2f}" if complete else "",
                f"{total - out:.2f}" if complete else "",
                f"{total:.2f}" + ("" if complete else f" ({len(holes)} holes)"),
                f"{total - sum(r.par for r in holes):+.2f}",
                *by_par,
                str(sum(r.over_par > 0.5 for r in holes)),
                # Handicap 1 is the hardest hole.
                f"{_spearman([r.over_par for r in holes], [-r.handicap for r in holes]):.2f}",
            ]
        )
    return _table(
        [
            "Course",
            "Out",
            "In",
            "Round",
            "Over par",
            "Par 3s",
            "Par 4s",
            "Par 5s",
            "Holes over +0.5",
            "Spearman vs handicap",
        ],
        rows,
    )


def ranking_table(results: list[HoleResult]) -> str:
    """Every hole, easiest against par first."""
    ranked = sorted(results, key=lambda r: r.over_par)
    return _table(
        [
            "#",
            "Hole",
            "Par",
            "Yards",
            "Handicap",
            "Expected",
            "Over par",
            "Rare visits",
        ],
        (
            [
                str(i),
                f"{COURSES[r.course]} {r.hole}",
                str(r.par),
                str(r.yards),
                str(r.handicap),
                f"{r.expected:.3f}",
                f"{r.over_par:+.3f}",
                "" if r.unvalued is None else f"{r.unvalued:.3f}",
            ]
            for i, r in enumerate(ranked, 1)
        ),
    )


def expert(results: list[HoleResult]) -> list[HoleResult]:
    """The Mario Open holes that play worse against par than every NES Open hole, hardest first."""
    nes = [r.over_par for r in results if not r.mario]
    if not nes:
        return []
    worst = max(nes)
    return sorted(
        (r for r in results if r.mario and r.over_par > worst),
        key=lambda r: -r.over_par,
    )


def new_at_nes_level(
    results: list[HoleResult], families: Mapping[str, list[str]]
) -> list[HoleResult]:
    """
    The Mario Open holes neither expert nor in a family with a NES Open hole: what
    Mario Open adds for a player at NES Open's level. Easiest first.
    """
    with_nes = {
        lineage
        for members in families.values()
        if any(m.startswith("nes_") for m in members)
        for lineage in members
    }
    hard = {r.lineage for r in expert(results)}
    return sorted(
        (
            r
            for r in results
            if r.mario and r.lineage not in hard and r.lineage not in with_nes
        ),
        key=lambda r: r.over_par,
    )


def hole_list(results: list[HoleResult]) -> str:
    return _table(
        ["Hole", "Par", "Yards", "Expected", "Over par"],
        (
            [
                f"{COURSES[r.course]} {r.hole}",
                str(r.par),
                str(r.yards),
                f"{r.expected:.3f}",
                f"{r.over_par:+.3f}",
            ]
            for r in results
        ),
    )


def markdown(results: list[HoleResult], families: Mapping[str, list[str]]) -> str:
    """
    The tables, each under a heading, for the doc's results. The expert holes and
    the new ones are measured against NES Open, so they need its solves too.
    """
    nes = [r for r in results if not r.mario]
    parts = [
        "### Courses",
        course_table(results),
        "### Every hole against par",
        ranking_table(results),
    ]
    if nes:
        worst = max(nes, key=lambda r: r.over_par)
        hard = expert(results)
        parts += [
            "### Expert holes",
            f"The {len(hard)} Mario Open holes that play worse against par than every NES "
            f"Open hole (the worst is {COURSES[worst.course]} {worst.hole}, "
            f"{worst.over_par:+.3f}), hardest first.",
            hole_list(hard),
        ]
        fresh = new_at_nes_level(results, families)
        parts += [
            "### New holes at NES Open level",
            f"The {len(fresh)} Mario Open holes that are not expert holes and share no "
            "family with a NES Open hole (`data/catalog/curation.json`), easiest first.",
            hole_list(fresh),
        ]
    return "\n\n".join(parts) + "\n"
