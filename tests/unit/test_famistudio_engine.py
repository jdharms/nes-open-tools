"""The edits `golf-famistudio-build` makes to the FamiStudio engine source."""

import pytest

from golf.core.famistudio_engine import FamiStudioBuildError, gate_engine_source

#: The engine's copy from its output buffer to the APU, as FamiStudio 4.5.3 has it
#: with smooth vibrato off, cut down to the lines the edits anchor on.
APU_COPY = """\
FAMISTUDIO_APU_PL1_VOL    = $4000
FAMISTUDIO_APU_PL1_SWEEP  = $4001
FAMISTUDIO_APU_PL1_LO     = $4002
FAMISTUDIO_APU_PL1_HI     = $4003
FAMISTUDIO_APU_PL2_VOL    = $4004
FAMISTUDIO_APU_PL2_SWEEP  = $4005
FAMISTUDIO_APU_PL2_LO     = $4006
FAMISTUDIO_APU_PL2_HI     = $4007
FAMISTUDIO_APU_TRI_LINEAR = $4008
    lda famistudio_output_buf      ; Pulse 1 volume
    sta FAMISTUDIO_APU_PL1_VOL
        cmp famistudio_pulse1_prev
        beq @no_pulse1_upd
@no_pulse1_upd:
    lda famistudio_output_buf+3    ; Pulse 2 volume
    sta FAMISTUDIO_APU_PL2_VOL
@no_pulse2_upd:
    lda famistudio_output_buf+9    ; Noise volume
    sta FAMISTUDIO_APU_NOISE_VOL
    lda famistudio_output_buf+10   ; Noise period
    sta FAMISTUDIO_APU_NOISE_LO

.endif
"""


def test_each_channel_copy_is_skipped_while_an_effect_holds_it():
    lines = gate_engine_source(APU_COPY).splitlines()

    def before(anchor: str, count: int) -> list[str]:
        at = next(i for i, line in enumerate(lines) if anchor in line)
        return [line.split(";")[0].strip() for line in lines[at - count : at]]

    assert before("; Pulse 1 volume", 8)[:5] == [
        "lda SfxSlot2Playing",
        "beq @golf_pulse1_free",
        "lda #$80",
        "sta famistudio_pulse1_prev",
        "bne @no_pulse1_upd",
    ]
    assert before("; Pulse 2 volume", 8)[:5] == [
        "lda SfxSlot1Playing",
        "beq @golf_pulse2_free",
        "lda #$80",
        "sta famistudio_pulse2_prev",
        "bne @no_pulse2_upd",
    ]
    assert before("; Noise volume", 4)[:2] == [
        "lda SfxSlot3Playing",
        "bne @golf_noise_held",
    ]
    # the label the noise skip lands on closes the block
    assert (
        lines[lines.index("    sta FAMISTUDIO_APU_NOISE_LO") + 1] == "@golf_noise_held:"
    )


def test_square_1_plays_on_the_hardwares_pulse_2():
    """The menu effects take pulse 1, and Square 1 usually has the tune."""
    lines = gate_engine_source(APU_COPY).splitlines()
    assert lines[:9] == [
        "FAMISTUDIO_APU_PL1_VOL    = $4004",
        "FAMISTUDIO_APU_PL1_SWEEP  = $4005",
        "FAMISTUDIO_APU_PL1_LO     = $4006",
        "FAMISTUDIO_APU_PL1_HI     = $4007",
        "FAMISTUDIO_APU_PL2_VOL    = $4000",
        "FAMISTUDIO_APU_PL2_SWEEP  = $4001",
        "FAMISTUDIO_APU_PL2_LO     = $4002",
        "FAMISTUDIO_APU_PL2_HI     = $4003",
        "FAMISTUDIO_APU_TRI_LINEAR = $4008",
    ]


def test_the_rest_of_the_source_is_untouched():
    gated = gate_engine_source(APU_COPY)
    kept = [line for line in gated.splitlines() if "golf" not in line.lower()]
    for line in APU_COPY.splitlines()[9:]:
        assert line in kept


@pytest.mark.parametrize(
    "missing",
    ["PL2_SWEEP", "; Pulse 1 volume", "; Pulse 2 volume", "; Noise volume", ".endif"],
)
def test_a_source_without_an_anchor_is_refused(missing):
    source = "\n".join(line for line in APU_COPY.splitlines() if missing not in line)
    with pytest.raises(FamiStudioBuildError, match="4.5.3"):
        gate_engine_source(source + "\n")


def test_a_source_with_an_anchor_twice_is_refused():
    with pytest.raises(FamiStudioBuildError):
        gate_engine_source(APU_COPY + APU_COPY)
