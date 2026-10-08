"""
Hole deltas: a derived hole as the cells and metadata that differ from its base.

A delta is data, never operations: metadata values that replace the base's, and for each
of the three tile grids the row count it ends with and the runs of cells that differ,
after the base's rows are moved up or down by one whole `row_offset`.
Applying one is a fixed, small piece of code, so a derived hole resolves to the same
content whatever happens to the editor's tools (ADR 0022, `docs/derived_holes.md`).

Both `diff` and `apply` work on a hole's canonical dict (`catalog.canonical_dict`):
everything that reaches the ROM, with terrain cut to its visible height. A delta
therefore never mentions hidden rows, the hole number or the `_debug` block.

```json
{
  "format": 1,
  "base": "nes_us/12",
  "metadata": {"par": 3, "distance": 190, "tee": {"x": 120, "y": 180}},
  "terrain": {"rows": 30, "cells": [[22, 9, "35 36"], [23, 9, "37 38"]]},
  "attributes": {"rows": 15, "cells": [[11, 4, "1"]]}
}
```

A run is `[row, column, values]`, with terrain and greens tiles as two-digit hex and
attribute palettes as decimal, separated by spaces. Rows are counted from the top, so a
hole cropped or extended at the bottom keeps every other cell's position.

`row_offset` is what a hole cropped or extended at the top has: the derived hole's
terrain row `r` is compared with the base's row `r + row_offset`, so 10 says the base's
top 10 rows are gone and -2 that two rows were added above it. It is even, since a
palette covers two terrain rows, and attribute row `r` is compared with the base's
`r + row_offset / 2`. The greens grid is the green's own and does not move. A delta
with no `row_offset` has one of 0.

A row with no base row to differ from, past either end of the base, is written whole.
"""

from typing import Any

FORMAT = 1

#: canonical keys a delta replaces whole
METADATA_KEYS = (
    "par",
    "distance",
    "handicap",
    "scroll_limit",
    "green",
    "tee",
    "flag_positions",
)
#: canonical keys holding a grid of cells, and whether their rows are hex strings
GRIDS = {"terrain": True, "attributes": False, "greens": True}

#: how many terrain rows one row of a grid covers; the greens grid takes no row offset
ROWS_PER_OFFSET = {"terrain": 1, "attributes": 2}

_KEYS = {"format", "base", "metadata", "row_offset", *GRIDS}


class DeltaError(ValueError):
    """A malformed delta, or one that does not fit the hole it is applied to."""


def _cells(grid: dict, hexadecimal: bool, what: str) -> list[list[int]]:
    """A canonical grid's rows as integers, checked against its width and height."""
    width = grid["width"]
    rows = (
        [[int(cell, 16) for cell in row.split()] for row in grid["rows"]]
        if hexadecimal
        else [list(row) for row in grid["rows"]]
    )
    if any(len(row) != width for row in rows):
        raise DeltaError(f"{what}: every row must have {width} cells")
    return rows


def _format_run(values: list[int], hexadecimal: bool) -> str:
    return " ".join(f"{value:02X}" if hexadecimal else str(value) for value in values)


def _parse_run(text: object, hexadecimal: bool, what: str) -> list[int]:
    if not isinstance(text, str) or not text:
        raise DeltaError(f"{what}: a run's values must be a non-empty string")
    try:
        values = [int(part, 16 if hexadecimal else 10) for part in text.split(" ")]
    except ValueError:
        raise DeltaError(f"{what}: bad run values {text!r}") from None
    if _format_run(values, hexadecimal) != text:
        raise DeltaError(f"{what}: run values {text!r} are not in canonical form")
    return values


def _grid_rows(grid: dict, cells: list[list[int]], hexadecimal: bool) -> list:
    if hexadecimal:
        return [_format_run(row, True) for row in cells]
    return cells


def _check_widths(base: dict, edited: dict, what: str) -> None:
    if base["width"] != edited["width"]:
        raise DeltaError(
            f"{what}: width {edited['width']} differs from the base's {base['width']}"
        )


def _base_row(old: list[list[int]], row: int, offset: int) -> list[int] | None:
    """The base row a derived row is compared with, or None when the base has none."""
    return old[row + offset] if 0 <= row + offset < len(old) else None


def _differing(old: list[list[int]], new: list[list[int]], offset: int) -> int:
    """How many cells of `new` a delta with this offset would have to write."""
    count = 0
    for number, row in enumerate(new):
        before = _base_row(old, number, offset)
        count += (
            len(row)
            if before is None
            else sum(a != b for a, b in zip(before, row, strict=True))
        )
    return count


def _grid_offset(name: str, row_offset: int) -> int:
    scale = ROWS_PER_OFFSET.get(name)
    return 0 if scale is None else row_offset // scale


def _best_row_offset(base: dict[str, Any], edited: dict[str, Any]) -> int:
    """The row offset that leaves the fewest cells to write, and 0 when none beats it.

    Every even offset that leaves the two terrains a row in common is tried. Among equal
    ones the smallest move wins, and a crop from the top over rows added there.
    """
    grids = {
        name: (
            _cells(base[name], GRIDS[name], f"base {name}"),
            _cells(edited[name], GRIDS[name], name),
        )
        for name in ROWS_PER_OFFSET
    }
    old_rows, new_rows = (len(rows) for rows in grids["terrain"])

    def cost(offset: int) -> int:
        return sum(
            _differing(old, new, _grid_offset(name, offset))
            for name, (old, new) in grids.items()
        )

    lowest = -((new_rows - 1) // 2) * 2
    highest = ((old_rows - 1) // 2) * 2
    candidates = sorted(
        range(lowest, highest + 1, 2), key=lambda offset: (abs(offset), -offset)
    )
    return min(candidates, key=cost, default=0)


def _diff_grid(
    base: dict, edited: dict, hexadecimal: bool, what: str, offset: int
) -> dict | None:
    old = _cells(base, hexadecimal, f"base {what}")
    new = _cells(edited, hexadecimal, what)
    runs = []
    for row_number, row in enumerate(new):
        before = _base_row(old, row_number, offset)
        column = 0
        while column < len(row):
            if before is not None and before[column] == row[column]:
                column += 1
                continue
            start = column
            while column < len(row) and (
                before is None or before[column] != row[column]
            ):
                column += 1
            runs.append(
                [row_number, start, _format_run(row[start:column], hexadecimal)]
            )
    if not runs and len(new) == len(old) and offset == 0:
        return None
    return {"rows": len(new), "cells": runs}


def diff(base: dict[str, Any], edited: dict[str, Any], base_id: str) -> dict[str, Any]:
    """The delta that turns `base` into `edited`, both canonical dicts.

    It holds only what differs, under the row offset that leaves the least to write, so
    it is the one delta `is_minimal` accepts for the pair.
    """
    for name in GRIDS:
        _check_widths(base[name], edited[name], name)
    delta: dict[str, Any] = {"format": FORMAT, "base": base_id}
    row_offset = _best_row_offset(base, edited)
    if row_offset:
        delta["row_offset"] = row_offset
    metadata = {key: edited[key] for key in METADATA_KEYS if edited[key] != base[key]}
    if metadata:
        delta["metadata"] = metadata
    for name, hexadecimal in GRIDS.items():
        grid = _diff_grid(
            base[name],
            edited[name],
            hexadecimal,
            name,
            _grid_offset(name, row_offset),
        )
        if grid is not None:
            delta[name] = grid
    return delta


def is_empty(delta: dict[str, Any]) -> bool:
    """Whether the delta changes nothing."""
    return not (set(delta) - {"format", "base"})


def _apply_grid(
    base: dict, change: object, hexadecimal: bool, what: str, offset: int
) -> dict:
    if not isinstance(change, dict) or set(change) != {"rows", "cells"}:
        raise DeltaError(f"{what}: expected an object with 'rows' and 'cells'")
    count, runs = change["rows"], change["cells"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise DeltaError(f"{what}: rows must be a positive integer, got {count!r}")
    if not isinstance(runs, list):
        raise DeltaError(f"{what}: cells must be a list of runs")
    width = base["width"]
    old = _cells(base, hexadecimal, f"base {what}")
    cells: list[list[int | None]] = [
        list(before)
        if (before := _base_row(old, row, offset)) is not None
        else [None] * width
        for row in range(count)
    ]
    last = (-1, -1)
    for run in runs:
        if (
            not isinstance(run, list)
            or len(run) != 3
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in run[:2]
            )
        ):
            raise DeltaError(f"{what}: a run is [row, column, values], got {run!r}")
        row, column, text = run
        values = _parse_run(text, hexadecimal, what)
        if not (0 <= row < count and 0 <= column <= width - len(values)):
            raise DeltaError(
                f"{what}: run at row {row}, column {column} is outside the "
                f"{width} x {count} grid"
            )
        if (row, column) <= last:
            raise DeltaError(
                f"{what}: runs must be in order and must not overlap, at row {row}, "
                f"column {column}"
            )
        last = (row, column + len(values) - 1)
        cells[row][column : column + len(values)] = values
    filled: list[list[int]] = []
    for number, row in enumerate(cells):
        if any(value is None for value in row):
            raise DeltaError(
                f"{what}: row {number} has no row of the base's {len(old)} to start "
                f"from and is not written whole"
            )
        filled.append([value for value in row if value is not None])
    result = dict(base)
    result["height"] = count
    result["rows"] = _grid_rows(base, filled, hexadecimal)
    return result


def apply(
    base: dict[str, Any], delta: object, base_id: str | None = None
) -> dict[str, Any]:
    """`base`, a canonical dict, with `delta` applied: the derived hole's canonical dict.

    `base_id`, when given, must be the base the delta names. Raises DeltaError for a
    delta that is malformed or does not fit the base.
    """
    if not isinstance(delta, dict):
        raise DeltaError(f"a delta must be an object, got {delta!r}")
    unknown = sorted(set(delta) - _KEYS)
    missing = sorted({"format", "base"} - set(delta))
    if unknown or missing:
        raise DeltaError(f"delta: missing fields {missing}, unknown {unknown}")
    if delta["format"] != FORMAT:
        raise DeltaError(
            f"unsupported delta format {delta['format']!r}; this code reads {FORMAT}"
        )
    if base_id is not None and delta["base"] != base_id:
        raise DeltaError(f"delta is for base {delta['base']!r}, not {base_id!r}")
    row_offset = delta.get("row_offset", 0)
    if (
        not isinstance(row_offset, int)
        or isinstance(row_offset, bool)
        or row_offset % 2
        or ("row_offset" in delta and row_offset == 0)
    ):
        raise DeltaError(
            f"row_offset must be a non-zero even number of rows, got {row_offset!r}"
        )
    if row_offset and not all(name in delta for name in ROWS_PER_OFFSET):
        raise DeltaError(
            f"a delta with a row_offset must hold {' and '.join(ROWS_PER_OFFSET)}"
        )
    result = {key: _copy(value) for key, value in base.items() if key not in GRIDS}
    metadata = delta.get("metadata", {})
    if not isinstance(metadata, dict) or set(metadata) - set(METADATA_KEYS):
        raise DeltaError(
            f"delta metadata may hold only {', '.join(METADATA_KEYS)}, got {metadata!r}"
        )
    for key, value in metadata.items():
        result[key] = _copy(value)
    for name, hexadecimal in GRIDS.items():
        if name in delta:
            result[name] = _apply_grid(
                base[name],
                delta[name],
                hexadecimal,
                name,
                _grid_offset(name, row_offset),
            )
        else:
            result[name] = _copy(base[name])
    return result


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def is_minimal(base: dict[str, Any], delta: dict[str, Any]) -> bool:
    """Whether the delta holds only cells and metadata that differ from the base.

    A delta that restates base cells would put the base's own data in the repository,
    which is what keeping deltas to cells is for.
    """
    return diff(base, apply(base, delta), delta["base"]) == delta


def changed_share(base: dict[str, Any], delta: dict[str, Any], grid: str) -> float:
    """The share of a grid's cells the delta rewrites, over the rows both holes have.

    A hole edited in place changes a small share. A large one means the hole moved
    within its grid, and the delta is then mostly the base hole displaced.
    """
    change = delta.get(grid)
    if change is None:
        return 0.0
    offset = _grid_offset(grid, delta.get("row_offset", 0))
    rows = len(base[grid]["rows"])
    shared = {row for row in range(change["rows"]) if 0 <= row + offset < rows}
    if not shared:
        return 0.0
    changed = sum(
        len(text.split(" ")) for row, _, text in change["cells"] if row in shared
    )
    return changed / (len(shared) * base[grid]["width"])
