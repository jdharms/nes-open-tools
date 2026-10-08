"""
NES Open Tournament Golf - Highlight Utilities

Shared utilities for drawing tile highlighting borders in terrain and greens renderers.
"""

import pygame
from pygame import Surface

from editor.controllers.highlight_state import HighlightState
from editor.controllers.view_state import ViewState

# Highlighting constants
HIGHLIGHT_COLOR = (255, 215, 0)  # Gold color
HIGHLIGHT_BORDER_WIDTH = 2

# Feature brush overlay colors (RGBA)
FEATURE_BRUSH_PAINT_COLOR = (255, 255, 255, 110)
FEATURE_BRUSH_ERASE_COLOR = (255, 80, 80, 110)
FEATURE_BRUSH_CURSOR_COLOR = (255, 255, 255, 220)


def draw_tile_border(
    screen,
    x: int,
    y: int,
    tile_size: int,
    color: tuple[int, int, int] = HIGHLIGHT_COLOR,
    border_width: int = HIGHLIGHT_BORDER_WIDTH,
):
    """
    Draw a colored border around a tile at the specified screen position.

    Args:
        screen: Pygame surface to draw on
        x: Screen x coordinate of tile
        y: Screen y coordinate of tile
        tile_size: Rendered size of tile in pixels
        color: Border color (default: gold)
        border_width: Border width in pixels (default: 2)
    """
    border_rect = pygame.Rect(
        x - border_width,
        y - border_width,
        tile_size + border_width * 2,
        tile_size + border_width * 2,
    )
    pygame.draw.rect(screen, color, border_rect, border_width)


def draw_dashed_line(
    surface,
    color: tuple[int, int, int],
    start_pos: tuple[int, int],
    end_pos: tuple[int, int],
    width: int = 1,
    dash_length: int = 5,
):
    """
    Draw a dashed line between two points.

    Args:
        surface: Pygame surface to draw on
        color: Line color (RGB tuple)
        start_pos: Starting position (x, y)
        end_pos: Ending position (x, y)
        width: Line width in pixels (default: 1)
        dash_length: Length of each dash in pixels (default: 5)
    """
    import math

    x1, y1 = start_pos
    x2, y2 = end_pos
    dx = x2 - x1
    dy = y2 - y1
    distance = math.sqrt(dx * dx + dy * dy)

    if distance == 0:
        return

    # Normalize direction
    dx /= distance
    dy /= distance

    # Draw dashes
    pos = 0
    drawing = True
    while pos < distance:
        next_pos = min(pos + dash_length, distance)
        if drawing:
            start = (int(x1 + dx * pos), int(y1 + dy * pos))
            end = (int(x1 + dx * next_pos), int(y1 + dy * next_pos))
            pygame.draw.line(surface, color, start, end, width)
        drawing = not drawing
        pos = next_pos


def render_feature_brush(
    screen: Surface, view_state: ViewState, highlight_state: HighlightState
):
    """Render the feature brush's stroke in progress and its cursor outline."""
    canvas_rect = view_state.canvas_rect
    scale = view_state.scale
    # Game pixel (x, y) covers a scale-sized square; the brush is centered on it
    radius = max(1, round((highlight_state.feature_brush_radius + 0.5) * scale))
    color = (
        FEATURE_BRUSH_ERASE_COLOR
        if highlight_state.feature_brush_erasing
        else FEATURE_BRUSH_PAINT_COLOR
    )

    def center(point: tuple[int, int]) -> tuple[int, int]:
        x, y = view_state.game_pixels_to_screen(point)
        return (x + scale // 2 - canvas_rect.x, y + scale // 2 - canvas_rect.y)

    overlay = Surface(canvas_rect.size, pygame.SRCALPHA)
    if highlight_state.feature_brush_points:
        for point in set(highlight_state.feature_brush_points):
            pygame.draw.circle(overlay, color, center(point), radius)
    if highlight_state.feature_brush_cursor:
        pygame.draw.circle(
            overlay,
            FEATURE_BRUSH_CURSOR_COLOR,
            center(highlight_state.feature_brush_cursor),
            radius,
            1,
        )
    screen.blit(overlay, canvas_rect.topleft)
