"""
Cycle tool - cycle through tiles in their bank/sub-bank.
"""

import pygame

from editor.core.constants import (
    GREENS_HEIGHT,
    GREENS_WIDTH,
    TERRAIN_WIDTH,
)

from .base_tool import ToolResult


class CycleTool:
    """Cycle tool - change tiles to next/previous in same sub-bank."""

    def __init__(self):
        # No persistent state needed - each click is independent
        pass

    def handle_mouse_down(self, pos, button, modifiers, context):
        """Handle mouse click - cycle tile at clicked position."""
        # Left click = previous, Right click = next
        if button not in (1, 3):
            return ToolResult.not_handled()

        view_state = context.view_state

        mode = context.state.mode

        if mode == "terrain":
            return self._cycle_terrain(view_state, pos, button, context)
        elif mode == "greens":
            return self._cycle_greens(view_state, pos, button, context)

        return ToolResult.not_handled()

    def handle_mouse_up(self, pos, button, context):
        return ToolResult.not_handled()

    def handle_mouse_motion(self, pos, context):
        return ToolResult.not_handled()

    def handle_key_down(self, key, modifiers, context):
        return ToolResult.not_handled()

    def handle_key_up(self, key, context):
        return ToolResult.not_handled()

    def on_activated(self, context):
        pass

    def on_deactivated(self, context):
        pass

    def reset(self):
        pass

    def get_hotkey(self) -> int | None:
        """Return 'C' key for Cycle tool."""
        return pygame.K_c

    def _cycle_terrain(self, view_state, pos, button, context) -> ToolResult:
        """Cycle terrain tile at clicked position."""
        tile = view_state.screen_to_tile(pos)
        if not tile:
            return ToolResult.handled()

        row, col = tile
        if not (0 <= row < len(context.hole_data.terrain) and 0 <= col < TERRAIN_WIDTH):
            return ToolResult.handled()

        current_tile = context.hole_data.terrain[row][col]

        # Get next/previous tile based on button
        if button == 1:  # Left click = previous
            new_tile = context.terrain_picker.get_previous_tile_in_subbank(current_tile)
        else:  # Right click = next
            new_tile = context.terrain_picker.get_next_tile_in_subbank(current_tile)

        if new_tile is None:
            return ToolResult(
                is_handled=True,
                message=f"Cycle: Tile 0x{current_tile:02X} not found in any bank",
            )

        # Check if tile actually changed (could wrap to same tile in single-tile bank)
        if new_tile == current_tile:
            return ToolResult.handled()

        # Push undo state before modification
        context.state.undo_manager.push_state(context.hole_data)

        # Apply change
        context.hole_data.set_terrain_tile(row, col, new_tile)

        direction = "←" if button == 1 else "→"
        message = f"Cycle: 0x{current_tile:02X} {direction} 0x{new_tile:02X}"
        return ToolResult.modified(message=message)

    def _cycle_greens(self, view_state, pos, button, context) -> ToolResult:
        """Cycle greens tile at clicked position."""
        tile = view_state.screen_to_tile(pos)
        if not tile:
            return ToolResult.handled()

        row, col = tile
        if not (0 <= row < GREENS_HEIGHT and 0 <= col < GREENS_WIDTH):
            return ToolResult.handled()

        current_tile = context.hole_data.greens[row][col]

        # Get next/previous tile based on button
        if button == 1:  # Left click = previous
            new_tile = context.greens_picker.get_previous_tile_in_subbank(current_tile)
        else:  # Right click = next
            new_tile = context.greens_picker.get_next_tile_in_subbank(current_tile)

        if new_tile is None:
            return ToolResult(
                is_handled=True,
                message=f"Cycle: Tile 0x{current_tile:02X} not found in any bank",
            )

        # Check if tile actually changed
        if new_tile == current_tile:
            return ToolResult.handled()

        # Push undo state before modification
        context.state.undo_manager.push_state(context.hole_data)

        # Apply change
        context.hole_data.set_greens_tile(row, col, new_tile)

        direction = "←" if button == 1 else "→"
        message = f"Cycle: 0x{current_tile:02X} {direction} 0x{new_tile:02X}"
        return ToolResult.modified(message=message)
