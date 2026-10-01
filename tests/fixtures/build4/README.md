# Frozen build 4 unfinished ROM

`unfinished.ips` was generated with commit
`6e2a59d5b5cb6fff9112f3783452155ac385f18f`, the last build 4 implementation
before scorecard QR protocol version 2. It exposes finish ABI 2 and emits
protocol version 1. The fixture has no player credentials.

The course contains 18 identical copies of NES Open's Japan hole 14, a par 4.
It was chosen as the smallest par 4 by combined compressed terrain, attributes
and greens size (504 bytes), among NES Open holes whose repeated yardage fits
the scorecard. No music is imported: the existing NES Open US theme is selected.
Only an IPS delta is checked in; the vanilla US ROM is supplied locally.

Manifest validation requires distinct hole IDs. The fixture catalog gives the
copies IDs `build4/copy_01` through `build4/copy_18`, each with the same source
and content hash. These aliases exist only in this fixture. All holes have wind
seed zero, and mercy tap-in is disabled.

`fixture.json` freezes the manifest, catalog, source commit, base ROM hash, IPS
hash, and historical QR routine addresses, RAM addresses and lengths. The
integration test uses the real current HTTP download and scan routes, runs the
downloaded historical code for both slots, and checks the stored scores and
absence of version 2 stats. It also checks guest downloads disable the QR splice.
Tests require neither dumped course files nor the historical checkout.

## Reproducing the fixture

Preserve this fixture when changing the current builder. A new historical build
should get a separate fixture rather than replacing these bytes.

With the vanilla US ROM and rehydrated NES Open courses available in the current
workspace, export the source commit to a temporary directory and run the
generator with that directory on `PYTHONPATH`:

```bash
mkdir -p /tmp/nes-build4
git archive 6e2a59d5b5cb6fff9112f3783452155ac385f18f | tar -x -C /tmp/nes-build4
PYTHONPATH=/tmp/nes-build4 .venv/bin/python tests/fixtures/build4/generate.py
```

The generator calls build 4's unchanged `build_unfinished` with the fixture
catalog and manifest. It selects the source hole deterministically and writes
both frozen files. No current assembly or unfinished recipe is substituted.
