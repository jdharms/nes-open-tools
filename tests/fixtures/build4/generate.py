"""Create the frozen fixture using the build 4 checkout named in README.md.

Run with that checkout on PYTHONPATH; this is not run by the tests.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from golf.core.patches.course import compress_holes
from golf.qr import payload, port
from golf.qr.port import layout
from golf.randomizer.build import BUILD_VERSION, build_unfinished
from golf.randomizer.catalog import US_ROM, Catalog, HoleId, HoleStore, RomSource
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.generate import generate
from golf.randomizer.manifest import Settings, Slot

SOURCE_COMMIT = "6e2a59d5b5cb6fff9112f3783452155ac385f18f"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    if BUILD_VERSION != 4:
        raise RuntimeError("use the frozen build 4 checkout, not the current builder")
    catalog = Catalog.load()
    store = HoleStore(ROOT / "courses")
    candidates = []
    for entry in catalog:
        if (
            entry.par == 4
            and isinstance(entry.source, RomSource)
            and entry.source.rom == US_ROM
            and 1000 <= entry.distance * 18 <= 9999
        ):
            compressed = compress_holes([store.load(entry)])[0]
            size = len(compressed.terrain + compressed.attributes + compressed.greens)
            candidates.append((size, entry.id))
    size, source_id = min(candidates)
    source = catalog[source_id]
    # Course requires distinct IDs. Each alias resolves to the same source data.
    copies = [
        replace(source, id=HoleId(f"build4/copy_{number:02d}"))
        for number in range(1, 19)
    ]
    fixture_catalog = Catalog(catalog.version, {entry.id: entry for entry in copies})
    manifest = generate(
        catalog,
        CurationSnapshot.load(),
        Settings(
            prng_seed="frozen-build4-qr",
            sources=frozenset({US_ROM}),
            music="nes_us",
            mercy_point=None,
        ),
    )
    manifest = replace(
        manifest,
        course=replace(
            manifest.course,
            holes=tuple(Slot(entry.id, 4, 0) for entry in copies),
        ),
    )
    vanilla = (ROOT / "nes_open_us.nes").read_bytes()
    unfinished = build_unfinished(manifest, fixture_catalog, store, vanilla)
    program = port.build()
    metadata = {
        "source_commit": SOURCE_COMMIT,
        "base_rom_sha1": hashlib.sha1(vanilla).hexdigest(),
        "unfinished_ips_sha256": hashlib.sha256(unfinished.ips).hexdigest(),
        "source_hole": str(source_id),
        "source_hole_compressed_bytes": size,
        "manifest": manifest.to_json(),
        "catalog": fixture_catalog.to_json(),
        "qr": {
            "bank": 2,
            "bank_size": 0x4000,
            "bank_origin": 0x8000,
            "header_size": 16,
            "symbols": {
                name: program.symbol(name) for name in ("QrBuildPayload", "QrBuildUrl")
            },
            "payload_address": layout.PAYLOAD,
            "payload_length": payload.PAYLOAD_LEN,
            "url_address": layout.URL,
            "url_length": payload.URL_LEN,
            "url_prefix": payload.URL_PREFIX,
            "strokes_address": layout.PER_HOLE_STROKES,
            "strokes_stride": layout.STROKE_STRIDE,
            "putts_address": layout.PER_HOLE_PUTTS,
            "putts_stride": layout.PUTT_STRIDE,
            "game_progress_address": layout.GAME_PROGRESS,
            "player_count_address": layout.PLAYER_COUNT,
            "game_mode_address": layout.GOLF_GAME_MODE,
            "splice_prg_offset": 0x3452E,
            "enabled_splice": "bddc",
            "disabled_splice": "ba85",
        },
    }
    (HERE / "unfinished.ips").write_bytes(unfinished.ips)
    (HERE / "fixture.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"{source_id}: {size} compressed bytes; IPS: {len(unfinished.ips)} bytes")


if __name__ == "__main__":
    main()
