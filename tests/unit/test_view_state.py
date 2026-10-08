"""Unit tests for the shared canvas rectangle and ToolContext.view_state."""

from editor.controllers.editor_state import EditorState
from editor.controllers.view_state import ViewState, canvas_rect
from editor.core.constants import (
    CANVAS_OFFSET_X,
    CANVAS_OFFSET_Y,
    STATUS_HEIGHT,
    TILE_SIZE,
    TOOL_PICKER_WIDTH,
)
from editor.tools.base_tool import ToolContext


def make_context(state, width=1280, height=1200):
    """Build a ToolContext with only the pieces the camera needs."""
    return ToolContext(
        hole_data=None,
        state=state,
        terrain_picker=None,
        greens_picker=None,
        forest_filler=None,
        screen_width=width,
        screen_height=height,
    )


def test_canvas_rect_excludes_pickers_toolbar_and_status_bar():
    rect = canvas_rect(1280, 1200)
    assert rect.x == CANVAS_OFFSET_X
    assert rect.y == CANVAS_OFFSET_Y
    assert rect.right == 1280 - TOOL_PICKER_WIDTH
    assert rect.bottom == 1200 - STATUS_HEIGHT


def test_canvas_rect_follows_screen_size():
    small = canvas_rect(1000, 800)
    large = canvas_rect(1600, 900)
    assert large.width - small.width == 600
    assert large.height - small.height == 100


def test_view_state_uses_current_state_each_access():
    state = EditorState()
    context = make_context(state)

    first = context.view_state
    assert isinstance(first, ViewState)
    assert first.canvas_rect == canvas_rect(1280, 1200)
    assert (first.offset_x, first.offset_y, first.scale) == (
        state.canvas_offset_x,
        state.canvas_offset_y,
        state.canvas_scale,
    )

    state.canvas_offset_x = 24
    state.canvas_offset_y = 48
    state.canvas_scale = 2
    context.screen_width = 1500
    context.screen_height = 900

    second = context.view_state
    assert second is not first
    assert second.canvas_rect == canvas_rect(1500, 900)
    assert (second.offset_x, second.offset_y, second.scale) == (24, 48, 2)


def test_view_state_converts_known_tile():
    state = EditorState()
    state.canvas_offset_x = 0
    state.canvas_offset_y = 0
    state.canvas_scale = 4
    view = make_context(state).view_state
    tile_px = TILE_SIZE * 4
    pos = (CANVAS_OFFSET_X + 3 * tile_px + 1, CANVAS_OFFSET_Y + 5 * tile_px + 1)
    assert view.screen_to_tile(pos) == (5, 3)


def test_tool_picker_column_is_outside_canvas():
    context = make_context(EditorState(), width=1280, height=1200)
    inside_picker = (1280 - TOOL_PICKER_WIDTH // 2, CANVAS_OFFSET_Y + 10)
    assert context.view_state.screen_to_tile(inside_picker) is None
    assert context.view_state.screen_to_game_pixels(inside_picker) is None
    just_inside = (1280 - TOOL_PICKER_WIDTH - 1, CANVAS_OFFSET_Y + 10)
    assert context.view_state.screen_to_tile(just_inside) is not None
