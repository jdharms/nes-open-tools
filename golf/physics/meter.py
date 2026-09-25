"""
The swing meters and the golfer's swing animation: what the frames a player
presses A on make of a shot. Bank 13's swing states ($AAED-$AC91) and the
animation frame bank 8's `RenderGolferAndClub` derives ($8000).

A swing is counted in passes of the swing loop, one per frame while the
golfer swings (the game waits for vblank once a pass until the ball is in the
air). A press 1 or 2 frames after the previous one is not seen (`MIN_PRESS_GAP`):

- **Backswing**: the power meter falls from $30 by the rate each pass
  (`SwingMeterRate`, halved for a putt). At 0 it bounces, losing the
  overshoot, and climbs; back at $30 it stops by itself, for no power. A press
  stops it after that pass's move. A putt's backswing starts by itself, on
  the first pass of the swing loop ($AAED); any other waits for a press.
- **Downswing**: the accuracy meter starts where the power meter stopped,
  fraction and all, and climbs twice as fast. At $4C the swing whiffs. A putt
  has no downswing: the power press launches it.
- **The animation**: `$D0/$D1` climbs by the rate each backswing pass. The
  power press reflects it about $31 and picks `SwingImpactFrame` from the
  animation frame then, and it climbs twice as fast after that until the
  animation reaches that frame. The animation frame is only worked out in the
  behind-the-golfer view, so a putt never reaches impact.

The ball launches on the pass after the last press. `frames_to_impact` is
then how many frames of flight pass before the animation reaches impact,
which is when the view may change and hi/lo stops being read.
"""

from dataclasses import dataclass

from golf.physics.tables import PhysicsTables

#: Where both meters start, and the power stop for no power.
METER_START = 0x30
#: The accuracy meter at or past this whiffs ($AC40).
ACCURACY_END = 0x4C
#: The power press reflects `$D1` about this ($ABE7).
ANIMATION_TOP = 0x31
#: The animation keeps climbing on the downswing below this frame, whatever
#: the impact frame ($AC16).
DOWNSWING_FRAMES = 0x05
#: `SwingImpactFrame` for the putter ($AC02).
PUTTER_IMPACT_FRAME = 0x05
#: The game ignores a press that comes fewer frames than this after the last.
MIN_PRESS_GAP = 3
#: A shot longer than this never reaches impact: its frames are not counted.
MAX_FRAMES = 1000


@dataclass(frozen=True)
class SwingTiming:
    power_stop: int
    """`$D6`: 0 is full power, $30 none."""
    accuracy_stop: int
    """`$D7`: $30 is dead centre. A putt's is its power stop, which the launch ignores."""
    frames_to_impact: int | None
    """As `ShotInput.frames_to_impact`; None for a putt, which never reaches impact."""


def meter_rate(tables: PhysicsTables, swing_speed: int, putting: bool) -> int:
    """$AB23-$AB40: the meters' step per pass, in 1/256ths."""
    rate = tables.swing_meter_rate[swing_speed]
    return rate >> 1 if putting else rate


def animation_frame(tables: PhysicsTables, animation: int) -> int:
    """$802E: how many thresholds `$D1` (the high byte of `animation`) exceeds."""
    high = animation >> 8
    frame = 0
    while high > tables.swing_animation[frame]:
        frame += 1
    return frame


@dataclass(frozen=True)
class Backswing:
    """The backswing, as the power meter stopped."""

    power: int
    """`$D6` and its fraction `$0587`: the power stop, 8.8 fixed point."""
    stopped_on: int
    """The pass it stopped on: the power press, or where it stopped by itself."""
    frame: int
    """The animation frame on that pass, which picks the impact frame."""
    animation: int
    """`$D0/$D1` after the press has reflected it."""

    @property
    def power_stop(self) -> int:
        return self.power >> 8


def backswing(
    tables: PhysicsTables, swing_speed: int, putting: bool, power_press: int
) -> Backswing:
    """$AB4C-$ABF5: the backswing that presses A on pass `power_press` (1 is the first)."""
    rate = meter_rate(tables, swing_speed, putting)
    power = METER_START << 8
    rising = False
    animation = 0
    frame = 0
    stopped_on = 0
    while stopped_on < power_press:
        stopped_on += 1
        frame = animation_frame(tables, animation)
        animation = (animation + rate) & 0xFFFF
        if not rising:
            power -= rate
            if power < 0:
                power = 0
                rising = True
        else:
            power += rate
            if power >> 8 >= METER_START:
                break
    power_stop = min(power >> 8, METER_START)
    if animation >> 8 < ANIMATION_TOP:
        animation = (2 * ANIMATION_TOP << 8) - (animation & 0xFF00) | animation & 0xFF
    return Backswing(power_stop << 8 | power & 0xFF, stopped_on, frame, animation)


def swing(
    tables: PhysicsTables,
    swing_speed: int,
    putting: bool,
    power_press: int,
    accuracy_press: int | None = None,
) -> SwingTiming | None:
    """
    The swing that presses A on backswing pass `power_press` (1 is the first)
    and again on pass `accuracy_press`, counting on through the downswing.

    A power meter that climbs back to $30 first stops there by itself, and
    then it is the power press that stops the accuracy meter, if it has not
    come yet. None when the accuracy meter runs off the end before a press.
    """
    rate = meter_rate(tables, swing_speed, putting)
    back = backswing(tables, swing_speed, putting, power_press)
    if putting:
        return SwingTiming(back.power_stop, back.power_stop, None)
    impact = tables.swing_impact_frame[back.frame]
    animation = back.animation

    presses = [p for p in (power_press, accuracy_press) if p is not None]
    press = next((p for p in presses if p > back.stopped_on), None)
    accuracy = back.power
    for _ in range(press - back.stopped_on if press is not None else MAX_FRAMES):
        frame = animation_frame(tables, animation)
        if frame < DOWNSWING_FRAMES or frame < impact:
            animation = (animation + 2 * rate) & 0xFFFF
        accuracy = (accuracy + 2 * rate) & 0xFFFF
        if accuracy >> 8 >= ACCURACY_END:
            return None

    # The launch pass, then the flight: each pass works out the animation
    # frame, and `frames_to_impact` counts the flight's passes short of impact.
    after_launch = 0
    for passes in range(MAX_FRAMES):
        frame = animation_frame(tables, animation)
        if passes and frame >= impact:
            return SwingTiming(back.power_stop, accuracy >> 8, after_launch)
        if passes:
            after_launch += 1
        if frame < impact:
            animation = (animation + 2 * rate) & 0xFFFF
    return SwingTiming(back.power_stop, accuracy >> 8, None)
