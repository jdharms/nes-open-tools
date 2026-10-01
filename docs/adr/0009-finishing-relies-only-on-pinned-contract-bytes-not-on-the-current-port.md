+++
status = "accepted"
date = 2026-10-01
area = "randomizer"
permanent = false
revisit_when = "The next finish ABI bump, which is also when to replace the zero placeholder fill with a recognizable magic value"
drafted_by = "Claude"
supersedes = []
+++

# Finishing relies only on pinned contract bytes, not on the current port

## Context

A randomized ROM is built in two stages (`docs/randomizer_devplan.md`): an unfinished ROM
once per seed, stored as an IPS, and a finished ROM per download. The finisher is always
the current release's code, but the unfinished ROM it finishes may come from any earlier
build version that shares its finish ABI.

Two things the QR finishing patches used came from the current port rather than from the
ROM being finished: `qr_credentials` took each placeholder's address from today's
assembly, and its `requires` check (`ScorecardQrPatch.is_applied`) compared all ten
trampoline bytes, including the far call's target, `QrShowCodes`, against today's build.
Either moving would make every stored seed of an earlier build version unfinishable. It
came up when protocol version 2 (ADR 0010) changed the port; that change happened to
leave both in place, because they come before everything it touched.

The finish ABI golden in `tests/unit/test_build.py` also listed the payload protocol
version as part of the ABI, though finishing writes none of the payload.

## Decision

> Anything the build-phase QR patch writes that the finisher relies on it being in a
> certain spot should have a test pinning it. Routines can generally move around, entry
> points can move around if they're only called by other code written as part of the
> build-phase and not as part of the finishing phase.

The QR half of the finish ABI is exactly these, pinned as literals in
`golf/core/patches/scorecard_qr.py` and in `tests/unit/test_qr_patch.py` and
`tests/unit/test_build.py`:

- `QrSeedId`, `QrPlayerId` and `QrMacKey` at `$8E5F`, `$8E67` and `$8E6F` in bank 2,
  8, 8 and 16 bytes, holding the `$00` fill (`PLACEHOLDER_ADDRESSES`). The finisher
  writes at these addresses; it no longer asks the port. Building `scorecard_qr` fails if
  the port puts a placeholder anywhere else.
- The splice at bank 13 `$852E` holding `$DCBD`, which `qr_disable` expects.
- The trampoline at `$DCBD` less the two bytes of its far call's target
  (`TRAMPOLINE_ENTRY_BYTES`): `JSR $85BA`, `JSR ExecuteFarCall`, bank `$02`, `RTS`.
  `is_applied` checks only these.

Builds 1 to 4 put these in the same place by definition: a change to any of them would
have been a finish ABI bump. The payload protocol version is not part of the ABI. The
unfinished image decides what a ROM sends, and the server accepts every version released.

## Rejected alternatives

- **Pin `QrShowCodes` too.** Simpler than masking two trampoline bytes, but it pins an
  entry point only build-phase code calls.
- **Look the addresses up per build version.** Needs every historical port kept
  buildable, and still breaks the moment one goes missing.
- **A recognizable magic fill in the placeholders now.** A better check that the bytes
  being overwritten really are placeholders, but the fill is itself part of ABI 2, and
  this change does not bump the ABI. Deferred to the next bump: see Consequences.

## Consequences

- The routine behind the trampoline, and everything in the image after the
  placeholders, can move between build versions without an ABI bump.
- Code added before `$8E5F` in the image has to fit around the placeholders; the build
  fails if it pushes them.
- At the next finish ABI bump, the placeholders can hold a magic value instead of zeros.
  The finisher would then be responsible for writing zeros over the magic for a guest
  ROM, so an unfinished or guest image still yields the all-zero IDs the server rejects:

  > I think the finishing process would be responsible for turning the magic fill into
  > the $00 fill.

## Sources

- `golf/core/patches/scorecard_qr.py`, `golf/core/patches/qr_credentials.py`,
  `golf/randomizer/build.py`; `tests/unit/test_qr_patch.py`, `tests/unit/test_build.py`
- `docs/scorecard_qr.md`, "Installing it: the patches"; ADR 0007 for finish ABI 2
- Claude Code session 2026-10-01 `07e081f7`. A build 4 unfinished ROM, built from the
  commit before the change, was finished by the changed code: its credentials landed and
  its version 1 payload verified.
