#!/usr/bin/env python3
"""Run every linter, formatter check and type checker the repo uses.

Checks: ruff (lint and format) and pyright over the Python, djLint over the Jinja
templates, Biome over the site's JS and CSS, and codespell over every tracked file for
British spellings. Each tool reads its configuration from pyproject.toml or
biome.jsonc. With --fix, the formatters rewrite files and the linters apply their safe
fixes; pyright and codespell have nothing to fix and run as checks.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from tools.dev.biome import ensure_binary

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = "server/templates"


def tracked_files() -> list[str]:
    """Every file git tracks, so codespell skips .venv, ROMs and dumped courses."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in listing.split("\0") if path]


def commands(fix: bool) -> list[tuple[str, list[str]]]:
    """(name, command) for each tool, in the order they run."""
    python = [sys.executable, "-m"]
    biome = [str(ensure_binary())]
    codespell = ("codespell", [*python, "codespell_lib", *tracked_files()])
    if fix:
        return [
            ("ruff lint", [*python, "ruff", "check", "--fix", "."]),
            ("ruff format", [*python, "ruff", "format", "."]),
            ("djlint format", [*python, "djlint", "--reformat", TEMPLATES]),
            ("djlint lint", [*python, "djlint", "--lint", TEMPLATES]),
            ("biome", [*biome, "check", "--write", "."]),
            ("pyright", [*python, "pyright"]),
            codespell,
        ]
    return [
        ("ruff lint", [*python, "ruff", "check", "."]),
        ("ruff format", [*python, "ruff", "format", "--check", "."]),
        ("djlint format", [*python, "djlint", "--check", TEMPLATES]),
        ("djlint lint", [*python, "djlint", "--lint", TEMPLATES]),
        ("biome", [*biome, "check", "."]),
        ("pyright", [*python, "pyright"]),
        codespell,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run every linter, formatter check and type checker the repo uses."
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="format files and apply safe lint fixes instead of only checking",
    )
    args = parser.parse_args(argv)

    failed = []
    for name, command in commands(args.fix):
        print(f"==> {name}", flush=True)
        returncode = subprocess.run(command, cwd=REPO_ROOT).returncode
        # djlint --reformat exits 1 whenever it rewrote a file
        if returncode != 0 and not (args.fix and name == "djlint format"):
            failed.append(name)

    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
