+++
status = "accepted"
date = 2026-10-01
area = "qr"
permanent = true
revisit_when = "A stat the league wants does not fit the payload's reserved flag bits, or the server needs per-hole penalties"
drafted_by = "Claude"
supersedes = []
+++

# Scorecard QR protocol version 2 adds fairways hit and penalty strokes

## Context

The league wanted two more stats from each round: fairways hit and penalty strokes. The
game tracks neither, so the ROM has to count them during play and the QR payload has to
carry them. Protocol version 1 is 36 bytes, every one in use apart from six reserved flag
bits, and every released ROM sends it.

The payload length must stay a multiple of 3, so base64 never pads, and the URL must stay
inside version 5-M's 84 characters, which caps the payload at 42 bytes
(`docs/scorecard_qr.md`).

## Decision

Protocol version 2 is 39 bytes: version 1's 32-byte body, three bytes of round stats,
then the MAC over all 35.

- Bytes 32-34: one fairway bit per hole for holes 1-18, least significant bit first from
  byte 32, then the round's penalty strokes in the top six bits of byte 34, held at 63.
  The reserved flag bits stay reserved.
- A fairway is hit when the tee shot of a par 4 or longer comes to rest on the fairway or
  the green. Par 3s never set their bit. A whiff on the tee makes the hole ineligible.
  A tee shot that holes out never comes to rest, so the ROM leaves its bit clear. The
  server stores one stroke on a par 4 or longer as a hit when it records the round, so
  stats read from the database count it; the stored payload keeps the bit as sent.

  > I would say count it as a FIR if it doesn't explode the code. We can always filter
  > out server side if we change our mind. Whiffs on the tee make you ineligible for a
  > FIR.

  > I think I do want it to count for stats purposes.

- A penalty stroke is one the game adds for water or out of bounds.
- Version 1 is accepted for good. Its rounds store fairways and penalties as NULL, not as
  misses and zero.
- Hole records stay 4/4 (ADR 0004).

The ROM side is the `round_stats` patch (`golf/core/patches/round_stats.py`), which
`scorecard_qr` requires.

## Rejected alternatives

- **Penalties in the six reserved flag bits, keeping more room elsewhere.** The fairway
  bits need three bytes regardless, and those three bytes have exactly six bits left.
- **Per-hole penalties.** Six bits per hole do not fit; a round total does.
- **Keeping the MAC'd body a multiple of four.** No payload length that is a multiple of
  3 and fits the QR also leaves a whole number of 32-bit words for the MAC body, so
  version 2 has a 3-byte tail. On cart, the tail costs nothing: the length byte is
  stored just past the body and the final block is read in place.
- **Shrinking the seed ID.** Seed IDs run to 62^10, which needs all eight bytes.

## Consequences

- URLs are 78 characters for version 2 and 74 for version 1. `/s/` tells them apart by
  length, and a version byte that does not match the length is malformed.
- The QR keeps its geometry: the same version and mask, with 6 pad code words instead of 10.
- The payload is 3 bytes from the 42-byte ceiling. Beyond that, the QR's version or
  error correction level would have to change.
- A round's stats are only as good as `round_stats`' hooks, which were found by static
  analysis; `docs/scorecard_qr.md`, "Round stats", records what has been confirmed on an
  emulator.

## Sources

- `docs/scorecard_qr.md`; `golf/qr/payload.py`; `golf/qr/port/payload.s`,
  `golf/qr/port/hash.s`; `golf/core/patches/round_stats.py`; `server/submissions.py`,
  `server/rounds.py`, `server/views.py`, migration 5 in `server/migrations.py`
- Claude Code session 2026-10-01 `07e081f7`
