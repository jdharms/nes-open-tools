"""The renders a seed's yardage book shows, made the first time a book asks for them.

A book shows each of its holes at the seed's pin: the whole hole with the flag drawn in,
the green, and that pin's overlay for the green. A hole here is its canonical JSON
(`golf.randomizer.catalog.canonical_json`), and its content hash names its directory under
`variants/` in the rangefinder directory, so a hole two seeds share is rendered once.

The renders are a cache: `render_rangefinder` clears them, and anything missing is
rendered again from the hole.
"""

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from golf.core.chr_tile import TILE_SIZE
from golf.rendering.rangefinder import PINS, VARIANTS, HoleRenderer


@dataclass(frozen=True)
class HoleRender:
    """One hole at one pin: its images as paths under the rangefinder directory."""

    main: str
    green: str
    flag: str
    width: int
    height: int


class HoleRenders:
    """Renders holes into `output_dir`, each image once.

    One lock covers the lot, so two requests for the same book do not render it twice,
    and the tilesets are read on the first render rather than at startup.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self._lock = threading.Lock()
        self._renderer: HoleRenderer | None = None

    def ensure(self, content_hash: str, pin: int, hole: dict[str, Any]) -> HoleRender:
        """The renders of `hole`, whose content hash is `content_hash`, at `pin`."""
        if not 0 <= pin < PINS:
            raise ValueError(f"a pin is 0-{PINS - 1}, got {pin}")
        directory = Path(VARIANTS) / content_hash
        main = directory / f"main_pin_{pin}.png"
        green = directory / "green.png"
        flag = directory / f"green_flag_{pin}.png"
        with self._lock:
            self._save(main, lambda renderer: renderer.main(hole, pin))
            self._save(green, lambda renderer: renderer.green(hole))
            self._save(flag, lambda renderer: renderer.flag(hole, pin))
        terrain = hole["terrain"]
        return HoleRender(
            main=main.as_posix(),
            green=green.as_posix(),
            flag=flag.as_posix(),
            width=terrain["width"] * TILE_SIZE,
            height=terrain["height"] * TILE_SIZE,
        )

    def _save(self, path: Path, render) -> None:
        """Render to `path` unless it is there, writing beside it and moving into place.

        A reader never sees half a file, and a render that fails leaves nothing behind.
        """
        target = self.output_dir / path
        if target.exists():
            return
        if self._renderer is None:
            self._renderer = HoleRenderer()
        image: Image.Image = render(self._renderer)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, scratch = tempfile.mkstemp(dir=target.parent, suffix=".png")
        try:
            with os.fdopen(handle, "wb") as file:
                image.save(file, "PNG")
            os.replace(scratch, target)
        except BaseException:
            Path(scratch).unlink(missing_ok=True)
            raise
