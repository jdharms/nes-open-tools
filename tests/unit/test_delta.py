"""Unit tests for hole deltas: what `diff` records and what `apply` accepts."""

import copy
import random

import pytest

from golf.randomizer import delta as hole_delta
from golf.randomizer.catalog import canonical_dict
from golf.randomizer.delta import DeltaError, apply, diff
from tests.synthetic_holes import synthetic_hole

BASE_ID = "nes_us/01"


@pytest.fixture
def base() -> dict:
    return canonical_dict(synthetic_hole(1))


def edited_hole():
    hole = synthetic_hole(1)
    hole.metadata["par"] = 3
    hole.metadata["tee"] = {"x": 90, "y": 200}
    hole.terrain[4][3] = 0x35
    hole.terrain[4][4] = 0x36
    hole.terrain[9][21] = 0x37
    hole.attributes[2][1] = 3
    hole.greens[0][0] = 0x10
    return hole


def test_an_unchanged_hole_has_an_empty_delta(base):
    delta = diff(base, copy.deepcopy(base), BASE_ID)
    assert delta == {"format": 1, "base": BASE_ID}
    assert hole_delta.is_empty(delta)
    assert apply(base, delta) == base


def test_a_delta_holds_only_what_differs(base):
    delta = diff(base, canonical_dict(edited_hole()), BASE_ID)
    assert delta == {
        "format": 1,
        "base": BASE_ID,
        "metadata": {"par": 3, "tee": {"x": 90, "y": 200}},
        "terrain": {"rows": 30, "cells": [[4, 3, "35 36"], [9, 21, "37"]]},
        "attributes": {"rows": 15, "cells": [[2, 1, "3"]]},
        "greens": {"rows": 24, "cells": [[0, 0, "10"]]},
    }
    assert not hole_delta.is_empty(delta)


def test_applying_a_delta_rebuilds_the_edited_hole(base):
    edited = canonical_dict(edited_hole())
    assert apply(base, diff(base, edited, BASE_ID), BASE_ID) == edited


def test_applying_a_delta_leaves_the_base_alone(base):
    before = copy.deepcopy(base)
    result = apply(base, diff(base, canonical_dict(edited_hole()), BASE_ID))
    result["attributes"]["rows"][0][0] = 2
    result["tee"]["x"] = 1
    assert base == before


def test_a_cropped_hole_records_its_rows_and_no_cells(base):
    hole = synthetic_hole(1)
    hole.terrain_height = 28
    hole.attributes = hole.attributes[:14]
    edited = canonical_dict(hole)
    delta = diff(base, edited, BASE_ID)
    assert delta["terrain"] == {"rows": 28, "cells": []}
    assert delta["attributes"] == {"rows": 14, "cells": []}
    assert apply(base, delta) == edited


def test_an_added_row_is_written_whole(base):
    hole = synthetic_hole(1)
    hole.terrain += [list(hole.terrain[0]), [0xDF] * 22]
    hole.terrain_height = 32
    hole.attributes.append([1] * 11)
    edited = canonical_dict(hole)
    delta = diff(base, edited, BASE_ID)
    assert [run[:2] for run in delta["terrain"]["cells"]] == [[30, 0], [31, 0]]
    assert all(len(run[2].split()) == 22 for run in delta["terrain"]["cells"])
    assert apply(base, delta) == edited


def test_a_hidden_row_is_never_in_a_delta(base):
    hole = synthetic_hole(1)
    hole.terrain.append([0x99] * 22)
    assert hole_delta.is_empty(diff(base, canonical_dict(hole), BASE_ID))


def test_is_minimal_refuses_a_delta_that_restates_the_base(base):
    delta = diff(base, canonical_dict(edited_hole()), BASE_ID)
    assert hole_delta.is_minimal(base, delta)
    restated = copy.deepcopy(delta)
    restated["terrain"]["cells"] = [[4, 2, "A2 35 36"], [9, 21, "37"]]
    assert apply(base, restated) == apply(base, delta)
    assert not hole_delta.is_minimal(base, restated)
    restated = copy.deepcopy(delta)
    restated["metadata"]["distance"] = base["distance"]
    assert not hole_delta.is_minimal(base, restated)


def test_changed_share_counts_the_rows_both_holes_have(base):
    hole = synthetic_hole(1)
    hole.terrain[0] = [0x35] * 22
    hole.terrain += [[0xDF] * 22, [0xDF] * 22]
    hole.terrain_height = 32
    hole.attributes.append([1] * 11)
    delta = diff(base, canonical_dict(hole), BASE_ID)
    assert hole_delta.changed_share(base, delta, "terrain") == pytest.approx(1 / 30)
    assert hole_delta.changed_share(base, delta, "greens") == 0.0


def test_a_delta_names_its_base(base):
    delta = diff(base, canonical_dict(edited_hole()), BASE_ID)
    with pytest.raises(DeltaError, match="not 'nes_us/02'"):
        apply(base, delta, "nes_us/02")


def test_a_width_change_is_refused(base):
    edited = copy.deepcopy(base)
    edited["terrain"]["width"] = 21
    edited["terrain"]["rows"] = [row[:-3] for row in edited["terrain"]["rows"]]
    with pytest.raises(DeltaError, match="width"):
        diff(base, edited, BASE_ID)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"format": 2}, "unsupported delta format"),
        ({"extra": 1}, "unknown"),
        ({"metadata": {"hole": 3}}, "metadata may hold only"),
        ({"metadata": [1]}, "metadata may hold only"),
        ({"terrain": {"rows": 30}}, "'rows' and 'cells'"),
        ({"terrain": {"rows": 0, "cells": []}}, "positive integer"),
        ({"terrain": {"rows": 30, "cells": {}}}, "list of runs"),
        ({"terrain": {"rows": 30, "cells": [[1, 2]]}}, r"\[row, column, values\]"),
        ({"terrain": {"rows": 30, "cells": [[1, "2", "35"]]}}, "row, column"),
        ({"terrain": {"rows": 30, "cells": [[30, 0, "35"]]}}, "outside"),
        ({"terrain": {"rows": 30, "cells": [[0, 21, "35 36"]]}}, "outside"),
        ({"terrain": {"rows": 30, "cells": [[0, -1, "35"]]}}, "outside"),
        ({"terrain": {"rows": 30, "cells": [[0, 0, ""]]}}, "non-empty string"),
        ({"terrain": {"rows": 30, "cells": [[0, 0, "ZZ"]]}}, "bad run values"),
        ({"terrain": {"rows": 30, "cells": [[0, 0, "5"]]}}, "canonical form"),
        ({"terrain": {"rows": 30, "cells": [[0, 0, "35  36"]]}}, "bad run values"),
        (
            {"terrain": {"rows": 30, "cells": [[3, 0, "35"], [2, 0, "35"]]}},
            "in order",
        ),
        (
            {"terrain": {"rows": 30, "cells": [[3, 0, "35 36"], [3, 1, "35"]]}},
            "overlap",
        ),
        ({"terrain": {"rows": 31, "cells": []}}, "row 30 has no row of the base"),
        ({"terrain": {"rows": 31, "cells": [[30, 1, "35"]]}}, "not written whole"),
        ({"attributes": {"rows": 15, "cells": [[0, 0, "0x1"]]}}, "bad run values"),
    ],
)
def test_a_malformed_delta_is_refused(base, change, message):
    delta = {"format": 1, "base": BASE_ID} | change
    with pytest.raises(DeltaError, match=message):
        apply(base, delta)


@pytest.mark.parametrize("delta", [None, [], {"format": 1}, {"base": BASE_ID}])
def test_a_delta_needs_its_format_and_base(base, delta):
    with pytest.raises(DeltaError):
        apply(base, delta)


def varied_hole(rows: int = 40):
    """A hole whose every terrain and attribute row is its own, so a moved row shows."""
    rng = random.Random(7)
    hole = synthetic_hole(1)
    hole.terrain = [[rng.randrange(0x100) for _ in range(22)] for _ in range(rows)]
    hole.terrain_height = rows
    hole.attributes = [[rng.randrange(4) for _ in range(11)] for _ in range(rows // 2)]
    return hole


def cropped(hole, top: int = 0, bottom: int = 0):
    """`hole` with whole rows, and their palettes, taken off either end."""
    result = varied_hole()
    end = len(hole.terrain) - bottom
    result.terrain = [list(row) for row in hole.terrain[top:end]]
    result.terrain_height = len(result.terrain)
    result.attributes = [list(row) for row in hole.attributes[top // 2 : end // 2]]
    return result


def test_a_hole_cropped_at_the_top_records_an_offset_and_no_cells():
    base = canonical_dict(varied_hole())
    edited = canonical_dict(cropped(varied_hole(), top=10))
    delta = diff(base, edited, BASE_ID)
    assert delta == {
        "format": 1,
        "base": BASE_ID,
        "row_offset": 10,
        "terrain": {"rows": 30, "cells": []},
        "attributes": {"rows": 15, "cells": []},
    }
    assert apply(base, delta) == edited
    assert hole_delta.is_minimal(base, delta)
    assert hole_delta.changed_share(base, delta, "terrain") == 0.0


def test_a_hole_cropped_at_both_ends_keeps_its_edits_as_cells():
    base = canonical_dict(varied_hole())
    hole = cropped(varied_hole(), top=4, bottom=6)
    hole.terrain[3][5] = (hole.terrain[3][5] + 1) % 0x100
    hole.attributes[2][0] = (hole.attributes[2][0] + 1) % 4
    edited = canonical_dict(hole)
    delta = diff(base, edited, BASE_ID)
    assert delta["row_offset"] == 4
    assert delta["terrain"] == {
        "rows": 30,
        "cells": [[3, 5, f"{hole.terrain[3][5]:02X}"]],
    }
    assert delta["attributes"] == {
        "rows": 15,
        "cells": [[2, 0, str(hole.attributes[2][0])]],
    }
    assert apply(base, delta) == edited
    assert hole_delta.changed_share(base, delta, "terrain") == pytest.approx(
        1 / (30 * 22)
    )


def test_rows_added_at_the_top_are_written_whole_under_a_negative_offset():
    base = canonical_dict(varied_hole(30))
    hole = varied_hole(30)
    hole.terrain = [[0xDF] * 22, [0xDE] * 22, *hole.terrain]
    hole.terrain_height = 32
    hole.attributes = [[2] * 11, *hole.attributes]
    edited = canonical_dict(hole)
    delta = diff(base, edited, BASE_ID)
    assert delta["row_offset"] == -2
    assert [run[:2] for run in delta["terrain"]["cells"]] == [[0, 0], [1, 0]]
    assert delta["attributes"]["cells"] == [[0, 0, " ".join(["2"] * 11)]]
    assert apply(base, delta) == edited
    # only the rows both holes have count toward the share
    assert hole_delta.changed_share(base, delta, "terrain") == 0.0


def test_a_hole_moved_and_back_at_full_height_takes_an_offset_too():
    base = canonical_dict(varied_hole())
    hole = cropped(varied_hole(), top=2)
    hole.terrain += [[0xDF] * 22, [0xDF] * 22]
    hole.terrain_height = 40
    hole.attributes.append([1] * 11)
    edited = canonical_dict(hole)
    delta = diff(base, edited, BASE_ID)
    assert delta["row_offset"] == 2
    assert [run[:2] for run in delta["terrain"]["cells"]] == [[38, 0], [39, 0]]
    assert apply(base, delta) == edited


def test_no_offset_is_taken_when_none_leaves_less_to_write(base):
    # the made-up hole repeats every four rows, so an offset of 4 fits as well as none
    hole = synthetic_hole(1)
    hole.terrain[0][0] = 0xA0
    hole.terrain[4][0] = 1
    delta = diff(base, canonical_dict(hole), BASE_ID)
    assert "row_offset" not in delta
    assert len(delta["terrain"]["cells"]) == 2


def test_is_minimal_refuses_an_offset_that_is_not_the_best():
    base = canonical_dict(varied_hole())
    edited = canonical_dict(cropped(varied_hole(), top=10))
    without = {
        "format": 1,
        "base": BASE_ID,
        "terrain": {
            "rows": 30,
            "cells": [
                [row, 0, text] for row, text in enumerate(edited["terrain"]["rows"])
            ],
        },
        "attributes": {
            "rows": 15,
            "cells": [
                [row, 0, " ".join(map(str, values))]
                for row, values in enumerate(edited["attributes"]["rows"])
            ],
        },
    }
    assert apply(base, without) == edited
    assert not hole_delta.is_minimal(base, without)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"row_offset": 3}, "non-zero even"),
        ({"row_offset": 0}, "non-zero even"),
        ({"row_offset": "2"}, "non-zero even"),
        ({"row_offset": True}, "non-zero even"),
        ({"row_offset": 2}, "must hold terrain and attributes"),
        (
            {"row_offset": 2, "terrain": {"rows": 30, "cells": []}},
            "must hold terrain and attributes",
        ),
        (
            {
                "row_offset": 2,
                "terrain": {"rows": 30, "cells": []},
                "attributes": {"rows": 15, "cells": []},
            },
            "terrain: row 28 has no row of the base's 30",
        ),
        (
            {
                "row_offset": -2,
                "terrain": {"rows": 30, "cells": []},
                "attributes": {"rows": 15, "cells": []},
            },
            "terrain: row 0 has no row of the base's 30",
        ),
    ],
)
def test_a_bad_row_offset_is_refused(base, change, message):
    delta = {"format": 1, "base": BASE_ID} | change
    with pytest.raises(DeltaError, match=message):
        apply(base, delta)
