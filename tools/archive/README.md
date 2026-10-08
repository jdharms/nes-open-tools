# Archived tools

One-off analysis scripts from earlier investigations. They have no entry points
and are not maintained; they are kept here so their approach is findable without
digging through git history. Run one with `uv run python -m tools.archive.<name>`,
and expect it may need fixing first.

| Script | What it was for |
|--------|-----------------|
| `analyze.py` | Statistics over hole JSON (tile frequencies, sizes, on-green tile counts) |
| `analyze_transform.py` | Reverse mappings through the compression tables' transform tables |
| `compare_traces.py` | Diffing `golf-write --trace-io` write traces against emulator read traces, from before the ROM layout was well understood |
| `find_neighbor.py` | Searching every hole for a specific tile-neighbor relationship |

The putting-surface analyzer is *not* here: it regenerates a file in `data/`
(`golf-analyze-putting`).
