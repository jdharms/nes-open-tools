"""
Feature Brush tool - paint fairways, bunkers and water as shapes, and the Out of Bounds
Brush, which paints out-of-bounds ground the same way.

Left-drag paints and right-drag erases, in course pixels. On release the tiles round the
stroke are chosen to draw the new shape (golf/algorithms/feature_brush.py). For the
Feature Brush the selected palette decides what is painted: 1 fairway, 2 bunker, 3 water.
The Out of Bounds Brush draws the line round the out-of-bounds ground and leaves inside
it the placeholder, for Forest Fill.
"""

import numpy as np
import pygame
from pygame import Rect

from editor.controllers.view_state import ViewState
from editor.core.constants import CANVAS_OFFSET_X, CANVAS_OFFSET_Y, STATUS_HEIGHT
from golf.algorithms.feature_brush import (
    FeatureChange,
    boundary_change,
    feature_change,
    stroke_mask,
)
from golf.formats.hole_data import HoleData

from .base_tool import ToolContext, ToolResult

MIN_RADIUS = 2
MAX_RADIUS = 16
DEFAULT_RADIUS = 6


class FeatureBrushTool:
    """Feature Brush tool - paint and erase fairways, bunkers and water."""

    NAME = "Feature Brush"

    def change(
        self, hole: HoleData, palette: int, stroke: np.ndarray, erase: bool
    ) -> FeatureChange:
        """What a finished stroke does to the hole."""
        return feature_change(hole, palette, stroke, erase)

    def __init__(self):
        self.radius = DEFAULT_RADIUS
        #: the button that started the stroke in progress, or None
        self.stroke_button: int | None = None
        #: the stroke in progress, in game pixels
        self.points: list[tuple[int, int]] = []

    def handle_mouse_down(self, pos, button, modifiers, context):
        if button not in (1, 3):
            return ToolResult.not_handled()
        if context.state.mode != "terrain":
            return ToolResult(
                is_handled=True, message=f"{self.NAME}: Only works in terrain mode"
            )
        if self.stroke_button is not None:
            return ToolResult.handled()
        point = self._view_state(context).screen_to_game_pixels(pos)
        if point is None:
            return ToolResult.handled()
        self.stroke_button = button
        self.points = [point]
        self._update_highlight(context, point)
        return ToolResult.handled()

    def handle_mouse_up(self, pos, button, context):
        if button != self.stroke_button:
            return ToolResult.not_handled()
        erase = button == 3
        points = self.points
        self._end_stroke(context)

        hole = context.hole_data
        palette = context.state.selected_palette
        change = self.change(
            hole, palette, stroke_mask(points, self.radius, hole), erase
        )
        if not change:
            return ToolResult(
                is_handled=True, message=f"{self.NAME}: Nothing to change"
            )
        context.state.undo_manager.push_state(hole)
        change.apply(hole)
        verb = "Erased" if erase else "Painted"
        return ToolResult.modified(
            terrain=True, message=f"{self.NAME}: {verb} ({len(change.tiles)} tiles)"
        )

    def handle_mouse_motion(self, pos, context):
        if context.state.mode != "terrain":
            return ToolResult.not_handled()
        point = self._view_state(context).screen_to_game_pixels(pos)
        if point is not None and self.stroke_button is not None:
            self._extend_stroke(point)
        self._update_highlight(context, point)
        return ToolResult.handled()

    def handle_key_down(self, key, modifiers, context):
        if key == pygame.K_ESCAPE and self.stroke_button is not None:
            self._end_stroke(context)
            return ToolResult(is_handled=True, message=f"{self.NAME}: Stroke canceled")
        if key in (pygame.K_COMMA, pygame.K_PERIOD):
            step = -1 if key == pygame.K_COMMA else 1
            self.radius = max(MIN_RADIUS, min(MAX_RADIUS, self.radius + step))
            context.highlight_state.feature_brush_radius = self.radius
            return ToolResult(
                is_handled=True, message=f"{self.NAME}: Radius {self.radius}"
            )
        return ToolResult.not_handled()

    def handle_key_up(self, key, context):
        return ToolResult.not_handled()

    def on_activated(self, context):
        context.highlight_state.feature_brush_radius = self.radius

    def on_deactivated(self, context):
        self._end_stroke(context)
        context.highlight_state.feature_brush_cursor = None

    def reset(self):
        self.stroke_button = None
        self.points = []

    def get_hotkey(self) -> int | None:
        """Return 'B' key for Feature Brush tool."""
        return pygame.K_b

    def _view_state(self, context: ToolContext) -> ViewState:
        canvas_rect = Rect(
            CANVAS_OFFSET_X,
            CANVAS_OFFSET_Y,
            context.screen_width - CANVAS_OFFSET_X,
            context.screen_height - CANVAS_OFFSET_Y - STATUS_HEIGHT,
        )
        return ViewState(
            canvas_rect,
            context.state.canvas_offset_x,
            context.state.canvas_offset_y,
            context.state.canvas_scale,
        )

    def _extend_stroke(self, point: tuple[int, int]) -> None:
        """Add the pixels from the stroke's last point to `point`, so a fast drag has no gaps."""
        last_x, last_y = self.points[-1]
        x, y = point
        steps = max(abs(x - last_x), abs(y - last_y))
        for step in range(1, steps + 1):
            self.points.append(
                (
                    last_x + round((x - last_x) * step / steps),
                    last_y + round((y - last_y) * step / steps),
                )
            )

    def _end_stroke(self, context: ToolContext) -> None:
        self.reset()
        if context.highlight_state is not None:
            context.highlight_state.feature_brush_points = None

    def _update_highlight(
        self, context: ToolContext, cursor: tuple[int, int] | None
    ) -> None:
        highlight = context.highlight_state
        if highlight is None:
            return
        highlight.feature_brush_cursor = cursor
        highlight.feature_brush_radius = self.radius
        highlight.feature_brush_erasing = self.stroke_button == 3
        highlight.feature_brush_points = (
            self.points if self.stroke_button is not None else None
        )


class BoundaryBrushTool(FeatureBrushTool):
    """Out of Bounds Brush tool - paint and erase out-of-bounds ground."""

    NAME = "Out of Bounds Brush"

    def change(
        self, hole: HoleData, palette: int, stroke: np.ndarray, erase: bool
    ) -> FeatureChange:
        return boundary_change(hole, stroke, erase)

    def get_hotkey(self) -> int | None:
        """Return 'O' key for Out of Bounds Brush tool."""
        return pygame.K_o
