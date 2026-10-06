# Mario Open versus NES Open: putting and green slopes

The rumor is partly true: **Mario Open doubles the slope vector in the cup
close-up, whereas NES Open does not.** The slope tile tables themselves,
putter power tables, and three putting meter rates are identical. The ordinary
green rolling calculation is also the same after accounting for relocated
code and RAM.

This comparison uses the original US and JP ROMs identified by
`golf/core/rom_utils.py` and `golf/core/jp_rom_utils.py`, not the experimental
[green slope patch](green_slope_physics.md) or the free-play output ROM.
Evidence is targeted `golf-rom-peek` disassembly plus execution of both ROMs'
actual routines under py65. No graphical emulator playthrough was performed.

## Identical tile values

| Data | US fixed-bank address | JP fixed-bank address | Length |
|---|---|---|---|
| X slope codes | $F359 | $F290 | 48 bytes |
| Y slope codes | $F389 | $F2C0 | 48 bytes |
| Magnitude fractional bytes | $F3B9 | $F2F0 | 7 bytes |
| Magnitude integer bytes | $F3C0 | $F2F7 | 7 bytes |

All 110 bytes compare exactly. The seven unsigned magnitudes, combining the
integer and fractional bytes, are:

| Class | Integer | Fraction | Combined value |
|---|---|---|---|
| Zero | $00 | $00 | $0000 |
| Gentle cardinal | $28 | $40 | $2840 |
| Gentle diagonal component | $28 | $A0 | $28A0 |
| Moderate cardinal | $50 | $80 | $5080 |
| Moderate diagonal component | $51 | $4A | $514A |
| Steep cardinal | $78 | $C0 | $78C0 |
| Steep diagonal component | $79 | $F4 | $79F4 |

The per-tile codes supply component magnitude and direction. Both releases
recognize the same dark slope tiles $30-$47 and light slope tiles $88-$9F.
Both use the same speed-dependent green slope calculation and cross-axis
scaling (dark versus light), followed by the same green friction calculation.
The routines are bank 13 $B1D5-$B270 in US and $B256-$B2F1 in JP; cross-axis
scaling is $B6DD versus $B75E.

## The extra JP calculation

The vector loader is fixed-bank $F300 in US and $F229 in JP. Both write the
six-byte slope vector at $EA-$EF. The US loader returns at $F358. The JP
loader instead ends with:

```asm
; JP $F281-$F28F
bit $97           ; JP ViewMode (US uses $98)
bvc done          ; bit 6 clear: no doubling
bpl done          ; bit 7 clear: no doubling
asl $EA
rol $EB           ; double unsigned X magnitude; sign in $EC stays unchanged
asl $ED
rol $EE           ; double unsigned Y magnitude; sign in $EF stays unchanged
done:
rts
```

Both bits set is the cup close-up ($C0). Ordinary green view is $40, the
behind-the-golfer view is $80, and overhead is $00, so those views do not take
the JP doubling path. Other values with both upper bits set would also take
it; this is a bit test, not an equality comparison with $C0.

This is live gameplay code: JP's green terrain classification calls the
loader at fixed-bank $EDAE after locating the tile in the green buffer.
It is not just a table used to draw the slope arrows.

The rest of the green calculation scales the vector by velocity and truncates
integer products. Consequently "twice the vector" does not guarantee exactly
twice every final velocity adjustment. It also affects the drag term reused
by the slope calculation; it is not simply an extra sideways force.

One executed example, with gentle dark tile $31 and an already rolling putt,
starting at X velocity 0 and Y velocity $004000:

| Release/view | Vector X magnitude | X velocity after green update | Y velocity after green update |
|---|---|---|---|
| US, ordinary or cup view | $2840 | 50 | 16271 |
| JP, ordinary view | $2840 | 50 | 16271 |
| JP, cup view | $5080 | 100 | 16221 |

These are the game's fixed-point register values for a single green update,
not pixels of travel or an entire putt's final position.

Both games slow motion near the cup: the position update uses one quarter of
putting velocity, and the remaining grounded-putt physics runs every fourth
frame. This code is US $AF75 and $B7A7, versus JP $AFF2 and $B828. The extra
JP slope scaling therefore exists within an already different time/position
scale near the cup. A plausible purpose is to strengthen break during that
close-up, but developer intent is not established by the code.

## Putter power and timing

| Data | US bank 13 | JP bank 13 | Values |
|---|---|---|---|
| Putter power, on green | $B8DC | $B95D | $5D, $73, $A0 |
| Putter power, off green | $B8E1 | $B962 | $40, $60, $80 |
| Swing-speed power factors | $B8EC | $B96D | $D7, $E3, $EE |
| Timing power curve | $B909 | $B98A | All 57 bytes identical |
| Meter rates, low/high | $AB46/$AB49 | $ABAF/$ABB2 | $0100, $0150, $01A0; halved for putting |

The launch routines are US $AD0A and JP $AD73. Tests execute both with matched
putter inputs, supplying the same green lie in place of the terrain probe,
and compare the launch's velocity and roll-budget bytes. All tested speeds,
power stops, and aim directions agree. This separates launch physics from
course layouts and the later cup-view difference.

## Verification and scope

`tests/integration/test_jp_putting_comparison_rom.py` retains the evidence:

- Byte equality for the slope tables, club/power/timing table block, meter
  rates, and the 128-entry trigonometry table.
- Both vector loaders executed for every possible tile byte in each of the
  four principal view modes: identical normal vectors, doubled JP cup vectors.
- 192 matched putter launches covering three speeds, eight power stops, and
  eight aim directions.
- Actual green rolling updates on all 48 slope tiles plus a flat tile, with
  four velocity pairs, including negative and low-speed components.
- The numerical cup-view example above.

This is not a complete comparison of cup collision, rim-in, lip-out, graphical
projection, or default player settings. It establishes an actual slope-response
difference without attributing every possible difference in putting feel to it.
The existing Python physics model uses US addresses and behavior; passing it
the JP ROM does not provide a valid JP simulation merely because these tables
match. A JP model would need the address map and this extra view-dependent step.

To make JP's vector loader behave like US, returning at JP $F281 would skip
its extra block. That is a concrete candidate for a future patch, not a patch
implemented or playtested by this investigation.
