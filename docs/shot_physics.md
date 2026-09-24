# Shot Physics

> **Note**: This document was written by Claude based on investigation requested by jdharms.

How the game moves the ball from the swing to where it stops: launch, flight, wind, bounce
and roll. Everything here comes from reading bank 13, and the Python model in
`golf/physics/` reproduces it frame for frame. None of it has been checked against the game
running in an emulator yet (see **Confirming it in the game**).

`golf-shots <rom>` prints carry and total for every club and swing speed from the model.

## Where it lives

`SwingSequenceEntry` (bank 13 `$AA09`) calls `CalcLaunchVector` (`$AD0A`) once per frame.
The first call (`ShotPhaseState` 0) launches the ball. Each later call (`ShotPhaseState` 1)
advances it one frame, until something sets `ShotPhaseState` to 2. The code runs from
`$AD0A` to `$B9A0`. Apart from that it uses only the fixed bank's `Mult8x8to16` (`$E743`),
`TrigLookupTable` (`$E7CB`), the RNG (`$D29C`) and the terrain probe `ProbeBallPosition`
(`$EDBC`).

## Units

- **Distance**: one pixel is two yards. The in-flight readout (`LD_A246`) takes the
  straight-line pixel distance with `IntegerSqrt` and doubles it, so both axes use the
  same scale.
- **Position**: `BallX` `$AE` and `BallY` `$B1/$B2` have 16 fraction bits below them
  (`$AC/$AD`, `$AF/$B0`). The playfield is `$B0` (176) pixels wide, and `BallX >= $B0` is
  out of bounds on any frame.
- **Velocity**: `VelocityDeltaX/Y` (`$DA-$DC`, `$DD-$DF`) are 24-bit two's complement in
  the same fixed point, so they are in pixels per frame. Even a full drive starts below one
  pixel per frame.
- **Height**: `$B3-$B6`, with `VerticalVelocity` (`$E0-$E3`) in the same units. Height
  `>> 23` is how many pixels the ball sprite lifts off its shadow.
- **Angles**: 256 to a turn. `Aiming` 0 is up the screen and `$40` is to the right.
  `WindDirection` uses the same scale for the direction the wind blows toward.

## Launch

The power is a chain of scalings. Each one is an 8x8 multiply that keeps the high byte, so
each is a fraction of 256:

1. **Timing**: `TimingPowerCurve[$38 − stop]`, where `stop` is where the power meter
   stopped (`$D6`). 0 is full power. Every shot loses 4 from this, except a *perfect
   drive*: 1W, full power, dead-centre accuracy, from tee or fairway. `$0592` flags that
   case; the label file had it as part of `BallSpeedMagnitude`.
2. **Club**: `ClubDistanceBaseTable`. The putter uses `PutterDistanceBySpeedTable` on the
   green, and `PutterDistAltTable` plus up to ±16 steps of random aim anywhere else.
3. **Lie**: in rough or sand, a penalty scale and then ± a random share of the power
   (`RoughPenalty*`/`RoughVariance`, `BunkerPenalty*`/`BunkerVariance`, one RNG draw).
   Clubs 0-3 read the wood columns.
4. **Swing speed**: `SwingSpeedMult`, 84%, 89% or 93% for slow, medium and fast.

The launch angle is `ClubLoftIndexTable[club]` plus the hi/lo step. `$ACFA` holds each
club's step: 1 for the woods up to 4 for the wedges, 0 for the putter. Holding Down adds the
step (a higher launch) and holding Up subtracts it. sin(angle) × power is the vertical
speed and cos(angle) × power the ground speed. The ground speed is then split along the aim
into X and Y velocity.

**Backspin** is a second budget, sin(base loft) × `$D0` × power, pointing opposite the aim
(`VelocityScaleX/Y` `$E4-$E7`). It ignores hi/lo. In the air it gives lift; on the ground
it brakes the roll until it is spent. Despite the name `VelocityScale`, it is not a scale.

**Curve**: how far the accuracy meter stopped from centre (`$D7` against `$30`), capped at
`$18`, minus the club's `ClubAimForgivenessTable` entry, times 8, is `AimDeviationMag`. The
side it stopped on is `AimDeviationDir`. Only the air frames use it, and first contact
clears it.

`PenaltyAccumulator` (`$D3`) collects 6 for a power stop of `$0A` or more, 3 for BACK 1 or
BACK 2, half the rough depth, or 2 in sand. `PenaltyMultiplierTable` turns the total into a
friction value for the first bounce, used when the shot has backspin (see below). TOP 1 and
TOP 2 do nothing ([topspin.md](topspin.md)).

## Every frame

In this order:

1. **Move**: position += velocity.
2. **Gravity**: vertical speed −= `$E001`. Height += vertical speed. If the height goes
   negative it is set back to zero and the frame counts as ground contact.
3. **Drag**: each axis loses 1/256 of itself, taken as the velocity's middle byte. It
   applies on the ground too.
4. **Out of bounds**: `BallX >= $B0` stops the ball with lie 5.
5. **Probe**: `ProbeBallPosition` sets the lie for the spot under the ball (see **Lies on
   a real hole**). In the overhead view only, a second probe offset by the ball's height
   looks for trees first (see **Trees**).
6. **Air or ground**: `ApplyWindEffect` in the air, `ProcessLanding` on contact.

Once the ball is rolling, every frame is a contact frame. Gravity pulls the vertical speed
negative, the height dips below zero, and the bounce leaves nothing.

## In the air: `ApplyWindEffect`

- **Wind** moves the ball's *position* directly, twice per frame, from the tenth air frame
  on (`WindDelayCounter`). It never changes the velocity. Its strength is `WindSpeed` ×
  min(height/2 + 2, 7), using the height's integer byte, so a high ball feels up to 3.5
  times the wind of one skimming the ground. The code computes a doubling for clubs 0-2 at
  `$B508` and then overwrites it at `$B511`, so it never applies.
- **Lift**: along each axis, airspeed (velocity minus the wind push) × backspin × 8 is
  added to the vertical speed when the ball moves against the spin, which is the normal
  case. This is why a high-lofted club hangs in the air.
- **Hook and slice**: airspeed × `AimDeviationMag` pushes sideways. The X-to-Y and Y-to-X
  terms are not symmetric. Descending, the X-to-Y term doubles and the Y-to-X term roughly
  quadruples, and their signs run opposite ways.

### Six wind directions are distorted

`LE7C3` reads cos(a) as `TrigLookupTable[a + $40]`, but the table only has 128 entries (a
half turn). `ApplyWindEffect` passes it `WindDirection & $7F`, so for directions whose low
seven bits are `$40` or more it reads the code after the table. The X component is right in
every case. Y is right in sign but not in size:

| Direction | Blows toward | Y the game uses | Correct Y |
|-----------|--------------|-----------------|-----------|
| `$40` / `$C0` | right / left | ±162 | 0 |
| `$50` / `$D0` | right-down / left-up | ±165 | ±98 |
| `$60` / `$E0` | down-right / up-left | ±1 | ±180 |
| `$70` / `$F0` | down-right / up-left | ±96 | ±236 |

(Out of 255; positive is down the screen.) So a crosswind to the right also pushes the ball
down the screen at 64% strength, and one to the left pushes it up. A wind at `$60` blows
almost due right instead of diagonally. Wind anchors are multiples of `$10`, so 6 of the 16
possible directions are affected.

It matters for shots aimed up the screen. A high PW at medium speed goes 101 yards with no
wind. With wind 9 it goes 87 yards in a pure crosswind to the right (`$40`), and 130 in one
to the left (`$C0`), as far as a diagonal tailwind (`$20`) takes it.

## On the ground: `ProcessLanding`

1. **First contact only.** On fairway or depth-0 rough, a random sideways kick
   proportional to the Y speed (`LD_B952`, table `$B9A1`). It reads the RNG state without
   advancing it. On the green, BACK 2 doubles the remaining backspin and BACK 1 multiplies
   it by 1.5, but only for clubs 4 and up and not for shots played from the rough.
2. **Bounce.** Vertical speed reverses and keeps 3/8 of itself. When nothing is left in its
   top byte it is zeroed and the ball rolls. The curve is cleared.
3. **Friction.** Each axis loses k/256 of itself. k depends on the lie, with a larger
   one-off value on first contact. A low shot takes up to `$3F` off any k of `$40` or more.
4. **Backspin brake.** 1.5 × the remaining backspin is taken from the velocity, then the
   lie's spend is subtracted from the budget. A budget that wraps past `$F0` counts as zero.
5. **Stop.** Once the backspin is gone and both velocities' middle bytes are within
   ±`stop` of zero, the ball stops.

| Lie | k per frame | k on first contact | Spin spent per frame | `stop` |
|-----|-------------|--------------------|----------------------|--------|
| Tee, fairway | 6; 7 high; 4 low | `$50` or `$30` on the RNG's low bit; +`$40` high, +`$10` low; BACK 1/2 not low, `PenaltyAccumulator` instead | 2 | 2 |
| Rough | depth × 4 + 15 | `PenaltyAccumulator` + `$40` | 5 | 4 |
| Bunker | `$14` | `$60` | all of it | 6 |
| Green | 2; 3 high; 1 low; +7 when `$CA` bit 7 is set | `PenaltyAccumulator` + `$20` (not low) | 1 | 1 |
| Water | 3, after a skip | — | 4 | 3 |
| Out of bounds | `$14` | `$70` | 8 | 6 |

- **Green**: the slope pushes the ball too. That model, and why it feels weak, is in
  [green_slope_physics.md](green_slope_physics.md).
- **Bunker**: the bounce and the spin are cancelled on contact. How hard the ball hit
  (`$0C` and `$19` in the vertical speed's top byte) and the RNG decide `BunkerDepth` 0-2.
  Any landing harder than the softest one plugs the ball on the spot.
- **Water**: the ball sinks, unless it arrives shallow (below `$30`) and the RNG draws
  `$E6` or more (about 1 in 10). Then it skips once, at half its vertical speed.

## Where randomness enters

Every draw uses the RNG ([seeded_wind.md](seeded_wind.md)). Only three things advance it:
the putter's aim wobble off the green, rough and bunker power variance at launch, and the
water-skip test. The first-contact kick, the fairway coin flip and the bunker depth read
the state without advancing it. So a shot from the tee or fairway that lands on grass is
decided by the starting RNG state. The coin flip is the only part of that which changes the
distance much (a medium 5I off the fairway finishes at 177 or 182 yards). The kick moves the ball a few
tenths of a pixel sideways.

## Lies on a real hole: `ClassifyProbePosition`

`ClassifyProbePosition` (`$EDEA`) takes a pixel and decides the lie from two things: the
palette of its 16x16 supertile, and its 8x8 terrain tile. The palette says what the plain
surface is: 1 fairway, 2 sand, anything else water. The tile then decides:

| Tile | Lie |
|------|-----|
| `$25` | light rough (`RoughDepth` 0) |
| `$27` | the palette's surface |
| `$35-$3C` | tee (lie 1; fairway is lie 0) |
| `$40-$7F` | shaped edges: a 1-bit mask per pixel (`$F020`); set is the palette's surface, clear is rough (light next to fairway, deep elsewhere) |
| `$80-$9B` | shaped rough: mask at `$F220`; set is deep rough, clear is out of bounds |
| `$3E`, `$9C-$9F` | trees in deep rough |
| `$A0-$BB` | trees, out of bounds |
| `$BC-$BF` | trees over the palette's surface |
| `$DF` | deep rough |
| everything else | out of bounds |

Tree tiles also report whether the pixel is trunk (colour 2 of a 2-bit mask at `$F3E2`,
flag `$0597`) or clear next to foliage (`$0598`).

Inside the green's 24x24-pixel box (`GreenX/Y`), each pixel is one tile of the green's own
24x24 grid. Tiles below `$30` are fringe and fall back to the terrain. Anything else is
lie 6. Tiles `$48-$87` set `$CA` bit 7 (more roll friction), and tiles `$30-$47` and
`$88-$9F` carry a slope, which `LF300` writes to `$EA-$EF`. The `$88-$9F` set also sets
`$CA` bit 6, which scales the slope differently.

Anything at `BallX >= $B0`, or at or below `TerrainBottomY` for the hole's scroll limit, is
out of bounds.

## Views, and what they change

`ViewMode` (`$98`) is set by the routines that draw each view: `$80` behind the golfer
(`LD_A499`), `$00` overhead (`LD_9AEF`), `$40` the green (`LD_A381`), `$FF` at hole start
and on resume. A shot starts behind the golfer, or on the green view for a putt.
Confirmed in Mesen: `$80` from the swing until the view changes, then `$00`.

After the physics each frame, the main loop (`$AA37-$AA9B`) decides whether to switch:

- **Behind the golfer**: on touchdown at any time. Otherwise not before the golfer's swing
  animation (bank 8, `$CF`) reaches its impact frame (`SwingImpactFrame`, `$058F`), and
  then once the ball starts to fall, leaves the scene (`$C5` = 0), or is `$3D` pixels
  (about 122 yards) out on the distance readout.
- **Overhead and green**: on touchdown, or once the ball is falling.

When it does switch, it goes to the green view if the ball is inside the green's box, not
in sand or water, and either on the green or already in the green view. Otherwise any view
other than overhead goes to overhead.

Switching to overhead redraws the course, and that redraw (`LD_A170`) zeroes the distance
readout. So does plugging a ball in sand, which redraws too.

### Trees

Each view has its own tree rule.

- **Behind the golfer**: `LD_BB6D` projects the ball into the scene (`LE87C`). The
  ball's position relative to the shot's origin (`$B8-$BC`) is rotated by the aim the
  scene was built along (`$BD`), then divided by depth, all in pixels: depth is 15 + the
  distance ahead; screen x is `$90` ± 208 × sideways ÷ depth; screen y is `$65` − 52 ×
  (5 × height − 22) ÷ depth. `LE9C8` then looks up the scene's depth and tile maps at
  that screen pixel (`$7AE6` and `$77E6`, 32 tiles a row). A tile standing 1-3 depth
  units behind the ball whose shape covers the pixel is a hit, and `$0599` becomes the
  tile number. Near the bottom of the screen it tests the pixels 3 either side. One
  quirk: the shape test repoints the depth map pointer at a mask table and never puts it
  back, so the second of two samples reads its depth from there.
- **Overhead**: `$AFF3` probes the spot the ball's sprite covers, `($B6:$B5) >> 7`
  pixels up the screen, while that is under 14. A trunk there and a leafy edge under the
  ball decrement `$0599` from 0 to `$FF`.

Whichever way it was set, `$0599` is acted on the next frame (`$B02C`). The first time, a
value of `$CC` or more stops the ball dead: ground velocity and backspin zeroed, still
falling. Less than that sends it back at a quarter speed on both axes. After that, for as
long as `$0599` stays set, the Y velocity is reversed and quartered again every frame.

### Hi/lo is read after the swing

`UpdateSwingHiLoAndAim` runs on every frame of the swing, not just while aiming, and keeps
running after launch until the swing animation reaches impact (`LD_ACB4`, from `$AC8F`).
The launch angle uses `SwingHiLo` at launch. The landing friction (a low shot's softer
first bounce and lower roll friction, a high shot's higher) uses it as it is when the ball
lands. So letting go of Up or Down just after the swing changes how the ball bites.

## The model

`golf/physics/` ports all of the above:

- `launch.py` and `flight.py` cover the launch and the air.
- `landing.py` covers ground contact.
- `terrain.py` is `ClassifyProbePosition`, over a hole from course JSON (`HoleGround`).
- `perspective.py` and `distance.py` cover the behind-the-golfer projection, its tree
  collision and the distance readout.
- `shot.py` runs the frame loop: the physics, the scene, then the view switch.

It reads its tables from whatever ROM it is given, and it takes the terrain from a
`Ground`: `UniformGround` for a driving range, or `HoleGround` for a real hole.

Three references check it (`tests/physics/`, run with `--physics`):

- `rom_oracle.py` runs the ROM's `CalcLaunchVector` alone under py65, with the terrain
  routed to the same `Ground`, and `RomTerrainProbe` runs `ClassifyProbePosition` over a
  hole loaded into RAM. `test_shot_rom.py` plays random shots through both over uniform
  and striped ground. `test_terrain_rom.py` compares every pixel of all 54 NES Open holes,
  and sampled pixels of the 83 Mario Open holes short enough for the vanilla ROM.
- `nes.py` is just enough of an NES to run the game's own frame loop: MMC1 banking, the
  controller, and the game's NMI handler at each vblank. `rom_game.py` loads a hole with
  the game's `InitHole` and plays a shot through `ShotSetupSequence` by pressing buttons,
  with the setup panels, the swing, the scene builder, the views and the trees all running
  as they do on a console. `test_game_rom.py` replays random shots from random lies on
  random holes in the model, and every register must agree after every frame.
- `test_scene_rom.py` calls the projection, the distance and the scene collision directly,
  with thousands of random inputs, over scenes the game's builder made.

## Not modelled yet

- **The cup and flagstick** (`LD_A884` → bank 9 `$81C4`), which run each frame in the
  green view: holing out, the slow-motion lip-out (`$0593`, physics every 4th frame) and
  bouncing off the pin (`$0595`, reversing the ball at `$AF49`). The model refuses with
  `UnportedBehaviourError` when the ball comes within reach of the cup, and ignores the
  cup otherwise, which is exact because the routine does nothing further away.
- **The scene builder** (bank 9 `$8829`, from `ShotSetupSequence`): it probes 64 × 20
  points ahead along the aim and draws the scene into the maps. The model takes a
  `PerspectiveScene` the ROM built; without one, the behind-the-golfer phase has no trees.
- **The swing animation's timing** (bank 8), which decides `frames_to_impact` (0-20
  frames, depending on how the swing was timed) and so when the view can first change.
  The model takes it as an input; the ROM oracle measures it.
- **Meter timing**: how many frames a stop takes at each swing speed. The meter rates are
  in `$AB46/$AB49`; the model takes the stops as given.
- **Holes over 46 rows.** `TerrainBottomY` in the vanilla ROM stops at scroll limit 9.
  Taller holes need the `wram_expansion` tables.
- **Views `$C0`/`$FF`**, where the loop halves the ball's movement and skips frames. They
  do not occur in a normal shot.
- **The drive-distance statistic** accumulated in `$05C0/$05C1`.

## Confirming it in the game

`test_game_rom.py` compares the model with the game's own frame loop, so what is left to
check on a console is that machine: that nothing it does not emulate (the PPU, sprite 0,
IRQs) changes a shot. Two cheap checks in Mesen:

- **A perfect 1W drive from the tee** (full power, dead-centre accuracy, medium speed, no
  wind) onto fairway should carry 235 yards and finish at 268 (`golf-shots` shows the
  same). Run in practice mode with the wind set to 0.
- **The wind distortion**: in practice mode set the wind to `$40` and hit a high wedge
  straight up the screen. The model says it lands short as well as right of a no-wind
  shot.
