"""Every module in the repo's packages imports cleanly as the first thing a fresh
interpreter loads.

Within one pytest process, modules are already imported by the time most tests
run, so a circular import that only bites when one particular module is imported
*first* goes unnoticed (golf.formats.hole_data -> golf.core -> course_validation
-> hole_data did, for the neighbor analyzers). Each module gets its own
subprocess here. Running it also catches modules nothing else imports, such as
editor.application, which no other test loads.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("golf", "server", "editor", "tools")


def _modules() -> list[str]:
    modules = []
    paths = [
        path for package in PACKAGES for path in sorted((ROOT / package).rglob("*.py"))
    ]
    for path in paths:
        parts = path.relative_to(ROOT).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))
    return modules


def _import_alone(module: str) -> tuple[str, str | None]:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return module, None
    return module, result.stderr.strip().splitlines()[-1]


MODULES = _modules()


def test_modules_were_found():
    assert MODULES, f"found no modules under {', '.join(PACKAGES)}"


@pytest.mark.parametrize("module", MODULES)
def test_every_module_imports_first(module):
    # Give xdist each fresh interpreter separately, rather than monopolizing
    # one worker with a thread pool after the rest of the suite has finished.
    name, error = _import_alone(module)
    assert error is None, f"{name}: {error}"
