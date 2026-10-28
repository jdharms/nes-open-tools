"""The tournament days patch and menu_trim's days: names, layout and code size."""

import pytest

from golf.core.patches.menu_trim import menu_trim_patches
from golf.core.patches.registry import PATCH_SPECS
from golf.core.patches.tournament_days import (
    CODE_LIMIT,
    CODE_ORIGIN,
    DAY_LIST_ADDR,
    DAY_LIST_VANILLA,
    DEFAULT_DAYS,
    STROKE_PLAY_TEXT,
    build_code,
    course_handler_bytes,
    day_list_bytes,
    normalize_days,
    title_layout,
    tournament_days_patch,
)


def test_days_default_to_thursday_through_sunday() -> None:
    assert normalize_days() == ("THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def test_days_are_uppercased() -> None:
    assert normalize_days(["day 1", "day 2", "day 3", "day 4"])[0] == "DAY 1"


@pytest.mark.parametrize(
    ("days", "match"),
    [
        (["THURSDAY", "FRIDAY", "SATURDAY"], "exactly 4"),
        (["THURSDAY", "FRIDAY", "SATURDAY", "WEDNESDAYS"], "1-9 characters"),
        (["THURSDAY", "FRIDAY", "SATURDAY", ""], "1-9 characters"),
        (["THURSDAY", "FRIDAY", "SATURDAY", "SUN.DAY"], "cannot both render"),
    ],
)
def test_days_that_cannot_be_drawn_are_refused(days: list[str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_days(days)


def test_the_day_list_is_four_entries_down_the_vanilla_rows() -> None:
    data = day_list_bytes()
    assert data[0] == 4
    entries = []
    for i in range(4):
        start = int.from_bytes(data[1 + 2 * i : 3 + 2 * i], "little") - DAY_LIST_ADDR
        end = data.index(0xFF, start)
        entries.append((data[start], data[start + 1], data[start + 2 : end].decode()))
    assert entries == [
        (0x0C, 0x0E, "THURSDAY"),
        (0x0C, 0x10, "FRIDAY"),
        (0x0C, 0x12, "SATURDAY"),
        (0x0C, 0x14, "SUNDAY"),
    ]


def test_the_longest_day_list_fits_the_space_it_moves_into() -> None:
    assert len(day_list_bytes(["WEDNESDAY"] * 4)) <= len(DAY_LIST_VANILLA)


def test_the_handler_is_as_long_as_what_it_replaces() -> None:
    assert len(course_handler_bytes()) == 15


def test_menu_trim_can_leave_the_course_select_alone() -> None:
    course_select = {
        "menu_trim_course_options",
        "menu_trim_course_option_text",
        "menu_trim_course_select_japan",
    }
    trimmed = {patch.name for patch in menu_trim_patches()}
    alone = {patch.name for patch in menu_trim_patches(course_select=False)}
    assert course_select <= trimmed
    assert alone == trimmed - course_select


def test_the_title_and_longest_day_are_centered_together() -> None:
    title_column, day_columns = title_layout(DEFAULT_DAYS)
    assert title_column == 13
    assert day_columns == [4, 6, 4, 6]
    for column, day in zip(day_columns, DEFAULT_DAYS, strict=True):
        assert column + len(day) == title_column - 1


def test_the_longest_days_stay_inside_the_card() -> None:
    title_column, day_columns = title_layout(["WEDNESDAY"] * 4)
    assert min(day_columns) >= 3
    assert title_column + len(STROKE_PLAY_TEXT) <= 29


def test_the_code_fits_for_the_longest_days() -> None:
    program = build_code(["WEDNESDAY"] * 4)
    assert program.origin == CODE_ORIGIN
    assert program.end <= CODE_LIMIT


def test_the_patch_requires_the_mirrors_and_the_days_menu() -> None:
    names = [requirement.name for requirement in tournament_days_patch().requires]
    assert names == ["course_mirrors", "menu_trim"]


def test_recipes_reach_both() -> None:
    assert "tournament_days" in PATCH_SPECS
    assert "course_select" in PATCH_SPECS["menu_trim"].params.__dataclass_fields__
    assert "days" in PATCH_SPECS["tournament_days"].params.__dataclass_fields__
