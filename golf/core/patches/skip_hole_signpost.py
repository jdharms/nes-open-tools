"""Skip the per-hole signpost card and its A/B wait, without removing round setup.

Bank 13 $81AB far-calls bank 12 $ABA5 after initializing a fresh hole.
The caller immediately rebuilds gameplay's PPU state, so the six-byte call
can be omitted. The separate round-entry/exit standee routine at $8064
is retained: it participates in returning completed rounds to the menu.
"""

from .byte_patch import BytePatch


def skip_hole_signpost_patch() -> BytePatch:
    """Go directly from fresh-hole setup to gameplay, without the signpost card."""
    return BytePatch(
        name="skip_hole_signpost",
        description="Skip the per-hole signpost card and its input wait",
        prg_offset=0x341AB,
        original=bytes.fromhex("20 72 D3 0C A5 AB"),
        patched=bytes([0xEA]) * 6,
    )
