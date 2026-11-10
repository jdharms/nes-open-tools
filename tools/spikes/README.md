# Spikes

Experimental scripts for ideas still being explored. They have no entry points, no
tests, and no promise of staying around or working: a spike either grows into a real
tool (moved out of here, with an entry point and tests) or is deleted. Run one with
`uv run python -m tools.spikes.<name>`. A spike's write-up, if it has one, sits beside
it as a Markdown file of the same name.

| Script | What it explores |
|--------|------------------|
| `player_skill.py` | Rating randomizer players from every hole score in a site database (`golf_site.db`), adjusting for the layout, terrain, pin and wind each player drew. Written up in `player_skill.md` |
