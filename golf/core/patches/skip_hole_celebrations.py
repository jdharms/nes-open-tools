"""Skip the post-hole retrieval/results scene and separate ace celebration.

Bank 13 $8D8F far-calls bank 11 $BEE5, which updates round stroke/putt
and versus-par totals before calling the post-hole scene at bank 12 $B094
from $BF90. Skip only that six-byte scene call, preserving the accounting
and its surrounding view/music setup. Bank 8 $9B21 saves notable-score
replays and is intentionally untouched.
"""

from .byte_patch import BytePatch
from .composite import CompositePatch


def skip_hole_celebrations_patch() -> CompositePatch[BytePatch]:
    """Keep score handling and the next signpost, without post-hole cutscenes."""
    return CompositePatch(
        name="skip_hole_celebrations",
        description="Skip ball retrieval/wave and the ace celebration",
        patches=[
            BytePatch(
                name="skip_hole_wave",
                description="Skip the post-hole scene after bank 11 updates round totals",
                prg_offset=0x2FF90,
                original=bytes.fromhex("20 72 D3 0C 94 B0"),
                patched=bytes([0xEA]) * 6,
            ),
            BytePatch(
                name="skip_ace_celebration",
                description="Jump past the ace-only celebration block",
                prg_offset=0x34350,
                original=bytes.fromhex("A6 99 BD 1F 01 C9 01 D0 20"),
                patched=bytes.fromhex("4C 79 83") + bytes([0xEA]) * 6,
            ),
        ],
    )
