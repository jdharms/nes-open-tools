"""
The cup and the flagstick: `UpdateBallAtCup` (bank 9 $81C4) and what the main
loop does around it (`LD_A884`, bank 13).

Near the pin the game switches to a close-up of the cup, `ViewMode` $C0. The
cup routine runs every frame there, and on each frame of the green view on
which the view switch runs. It works in the close-up's screen coordinates: the
ball's offset from the flag is turned so the shot's aim points up the screen,
scaled, and the hole is a fixed outline of screen pixels (`cup_top` and
`cup_bottom`).

- **Holing out**: two or more frames over the cup, moving slowly.
- **Rim-in**: a ball that crosses the cup, leaves it on the far side and is
  rolling too slowly to hop out drops in anyway.
- **Lip-out**: one that leaves it faster, and near the middle, hops out in slow
  motion (the physics runs every 4th frame) at half speed.
- **The flagstick**: a ball that reaches the pin, on the ground or low in the
  air, bounces back off it at half speed, once per shot. Never on a putt.

The close-up changes the physics too, see `CUP_VIEW` in `golf.physics.shot`.
"""

from golf.physics.arith import MASK8, MASK16, byte, halve, is_negative, mul8
from golf.physics.perspective import rotate
from golf.physics.state import Ball
from golf.physics.tables import PhysicsTables

#: `cup_y` when the ball is out of the cup's reach ($82B4).
OUT_OF_REACH = 0xF0

#: How far across the aim line (in the rotated offset's middle byte) the cup
#: view reaches: 6 while it is open, 5 to open it ($81FC).
REACH_ACROSS = 0x06
REACH_ACROSS_TO_OPEN = 0x05
#: The rows of the close-up the ball may be in: from $54, and below $C4 to open it.
TOP_ROW = 0x54
BOTTOM_ROW_TO_OPEN = 0xC4
#: Higher than this ($B6:$B5 >> 2) before its first bounce, the ball flies over.
REACH_HEIGHT = 0x20

#: Slower than this (`speed`), a ball over the cup drops in on its 2nd frame there.
HOLING_SPEED = 0x1C
#: A ball leaving the cup below this row went out the far side.
FAR_EDGE_ROW = 0xB5
#: Leaving at this speed or more, it lips out; slower, it drops in.
LIP_OUT_SPEED = 0x28
#: Leaving at this speed or more after the flagstick, it just rolls on.
FLAGSTICK_ROLL_ON_SPEED = 0x18


def speed(ball: Ball) -> int:
    """
    $8425: |vx| + |vy|, each the velocity's middle byte (negated alone, as a
    byte, when the velocity is negative), capped at $FF.
    """

    def size(v: int) -> int:
        middle = byte(v, 1)
        return -middle & MASK8 if is_negative(v, 24) else middle

    return min(size(ball.vx) + size(ball.vy), MASK8)


class Cup:
    """
    `UpdateBallAtCup` for one shot. `aim` is `Aiming` ($B7) and `putting` is
    `MaybeIsPuttingFlag` ($D4): the shot started on the green.
    """

    def __init__(self, flag_x: int, flag_y: int, aim: int, putting: bool, tables):
        self.flag_x = flag_x
        self.flag_y = flag_y
        self.aim = aim
        self.putting = putting
        self.tables: PhysicsTables = tables

    def update(self, ball: Ball, cup_view: bool) -> None:
        """$81C4, once per frame the main loop reaches it."""
        lift = self._place(ball, cup_view)
        if lift is None:
            ball.cup_y = OUT_OF_REACH
            return
        if ball.cup_slow_motion & 0x80:
            self._hop(ball)
            return
        ball.cup_bob &= 0x00FF
        self._over_cup(ball, lift)
        self._flagstick(ball)

    def _place(self, ball: Ball, cup_view: bool) -> int | None:
        """
        $81C4-$828A: put the ball on the close-up's screen, writing `cup_x`
        and `cup_y`. Returns its height there, or None when it is out of reach.
        """
        dx = ((ball.x >> 8) - self.flag_x) << 3 & MASK16
        dy = (self.flag_y - (ball.y >> 8 & MASK16)) << 3 & MASK16
        across_aim, along_aim = rotate(dx, dy, (self.aim + 0x80) & MASK8, self.tables)
        across = byte(across_aim, 1)
        if across & 0x80:
            across = -across & MASK8
        if across >= REACH_ACROSS or not cup_view and across >= REACH_ACROSS_TO_OPEN:
            return None

        # x = 20 * across, keeping the high byte of a 16-bit product.
        x = across_aim & MASK16
        x = (x << 2 & MASK16) + x & MASK16
        ball.cup_x = (byte(x << 2, 1) + 0x80) & MASK8

        along = (byte(along_aim, 1) + 4) & MASK8
        if along >= 0x14:
            return None
        # y = 6 * along, byte by byte: the high byte's carry out is lost.
        fraction = byte(along_aim, 0)
        doubled = (along << 8 | fraction) << 1 & MASK16
        low = (doubled & MASK8) + fraction
        high = ((doubled >> 8) + along + (low >> 8)) & MASK8
        y = ((high << 8 | low & MASK8) << 1 & MASK16) >> 8
        row = (0xC6 - y) & MASK8
        if row < TOP_ROW or not cup_view and row >= BOTTOM_ROW_TO_OPEN:
            return None
        ball.cup_y = row

        height = ball.height >> 16 & MASK16
        if height >= 0x200:
            return None
        lift = height >> 2
        if not ball.bounce_state and lift >= REACH_HEIGHT:
            return None
        return lift

    def _hop(self, ball: Ball) -> None:
        """
        $829B: a lip-out's hop, one frame of it. Gravity is $4E a frame, or 2
        after a rim-in ($05C2), which cannot happen here. The hop ends when it
        comes back down to the lip.
        """
        gravity = 0x02 if ball.cup_drop else 0x4E
        ball.cup_bob_speed = (ball.cup_bob_speed + gravity) & MASK16
        ball.cup_bob = (ball.cup_bob + ball.cup_bob_speed) & MASK16
        if not ball.cup_bob & 0x8000:
            ball.cup_slow_motion = (ball.cup_slow_motion + 1) & MASK8
            ball.cup_bob &= 0x00FF

    def _over_cup(self, ball: Ball, lift: int) -> None:
        """$82B9: is the ball over the cup, and does it drop in?"""
        if lift:
            ball.cup_frames = 0
            return
        column = self._column(ball.cup_x)
        if column is None or not (
            self.tables.cup_top[column] <= ball.cup_y < self.tables.cup_bottom[column]
        ):
            self._left_cup(ball)
            return
        ball.cup_last_x = ball.cup_x
        ball.cup_last_y = ball.cup_y
        if ball.cup_entry_y == 0xFF:
            ball.cup_entry_y = ball.cup_y
        ball.cup_frames = (ball.cup_frames + 1) & MASK8
        if speed(ball) < HOLING_SPEED and ball.cup_frames >= 2:
            _hole_out(ball)

    @staticmethod
    def _column(x: int) -> int | None:
        """$82C3: the outline's column for screen x, mirrored about the centre."""
        column = x - 0x58
        if column < 0 or column >= 0x50:
            return None
        if column >= 0x28:
            column = 0x4F - column
        return column

    def _left_cup(self, ball: Ball) -> None:
        """
        $8315: the ball is not over the cup. If it was last frame, and it has
        landed and gone out the far side, it either lips out or drops in.
        """
        if not ball.cup_frames:
            return
        if (
            not ball.landing_processed
            or speed(ball) >= FLAGSTICK_ROLL_ON_SPEED
            and ball.flagstick
            or ball.cup_y < FAR_EDGE_ROW
        ):
            ball.cup_frames = 0
            return
        if speed(ball) >= LIP_OUT_SPEED:
            self._lip_out(ball)
        else:
            self._rim_in(ball)

    def _rim_in(self, ball: Ball) -> None:
        """
        $833E: the ball goes in after all. The screen position goes back to
        where it was last over the cup, pushed down to the cup's bottom edge.
        """
        ball.cup_x = ball.cup_last_x
        column = self._column(ball.cup_x)
        # $819A clamps where $82C3 refuses, but the ball was over the cup at
        # `cup_last_x`, so the column is always in range.
        ball.cup_y = self.tables.cup_bottom[column or 0]
        if not 0x6A <= ball.cup_x < 0x95:
            # $8393: off to one side, it drops in sideways. $05C2 sets how fast.
            drop = (speed(ball) - 0x10) & MASK8
            ball.cup_drop = 0x08 if drop & 0x80 or drop < 0x08 else drop
        elif ball.cup_entry_y < FAR_EDGE_ROW:
            ball.cup_slow_motion = (ball.cup_slow_motion + 1) & MASK8
            if not ball.cup_slow_motion:
                # Only from $FF, which the slow motion never leaves here.
                self._lip_out(ball)
                return
        _hole_out(ball)

    def _lip_out(self, ball: Ball) -> None:
        """$8359: near the middle, the ball hops out of the cup at half speed."""
        if 0x60 <= ball.cup_x < 0xA0:
            high, low = mul8(min(speed(ball), 0x50), 0x12)
            ball.cup_bob_speed = -(high << 8 | low) & MASK16
            ball.cup_slow_motion = 0xFF
            ball.cup_bob = 0xFFFF
            self.halve_speed(ball)
        ball.cup_frames = 0

    def _flagstick(self, ball: Ball) -> None:
        """$8445: the ball touches the pin; the physics bounces it next frame."""
        if self.putting or ball.flagstick:
            return
        if 0x6F <= ball.cup_x < 0x92 and 0xAF <= ball.cup_y < 0xBA:
            ball.flagstick = (ball.flagstick - 1) & MASK8

    def halve_speed(self, ball: Ball) -> None:
        """Bank 13 `LD_A8B6`: the ball loses half its speed, or 3/4 on a putt."""
        for _ in range(2 if self.putting else 1):
            ball.vx = halve(ball.vx)
            ball.vy = halve(ball.vy)


def _hole_out(ball: Ball) -> None:
    """$830D: `ShotPhaseState` 2 and `MaybeHoleCompleteFlag`."""
    ball.stopped = True
    ball.holed = (ball.holed + 1) & MASK8
