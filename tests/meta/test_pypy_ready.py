"""
The difficulty solver, and the ball physics under it, stay runnable under PyPy
3.11, which plays shots about ten times faster than CPython
(`docs/hole_difficulty.md`). PyPy has no 3.12 yet, so nothing they
import may use 3.12-only syntax, and they must not import the patch package,
which does.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENTRY_POINTS = ("golf.difficulty.solver", "tools.research.difficulty")

PROBE = """
import json, sys
for name in {entry_points!r}:
    __import__(name)
print(json.dumps({{name: getattr(module, "__file__", None) for name, module in sys.modules.items()}}))
"""


def _loaded() -> dict[str, str | None]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(entry_points=ENTRY_POINTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_solver_does_not_import_the_patches():
    patches = sorted(name for name in _loaded() if name.startswith("golf.core.patches"))
    assert not patches, (
        f"the solver imports {patches}; see golf/core/rng.py and clubs.py"
    )


def test_the_solver_parses_as_python_3_11():
    for name, file in _loaded().items():
        if file is None or not file.startswith(str(ROOT)) or "/.venv/" in file:
            continue
        source = Path(file).read_text()
        try:
            ast.parse(source, filename=file, feature_version=(3, 11))
        except SyntaxError as error:
            raise AssertionError(f"{name} is not Python 3.11: {error}") from None
