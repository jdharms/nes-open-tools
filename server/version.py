"""The site's release, read from the git checkout it runs from (ADR 0005).

A deploy checks out a `server-v*` tag, so the checkout names its own release. Anywhere
else, `git describe` says how far past the last release it is and whether tracked files
have changed, e.g. `v1.0.2-10-gc66d426-dirty`.
"""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

#: a server release's tag is this prefix and the version, e.g. `server-v1.0.2`
TAG_PREFIX = "server-"


def site_version(checkout: Path) -> str | None:
    """The release `checkout` is at, without the tag prefix, or None when git can't say.

    The service runs as a different user from the one who owns the checkout, which git
    refuses to read unless the directory is named safe; this only reads, so it is.
    """
    command = [
        "git",
        "-c",
        f"safe.directory={checkout}",
        "describe",
        "--tags",
        "--match",
        f"{TAG_PREFIX}v*",
        "--dirty",
    ]
    try:
        result = subprocess.run(
            command, cwd=checkout, capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or error
        log.warning("no site version from git: %s", str(detail).strip())
        return None
    return result.stdout.strip().removeprefix(TAG_PREFIX)
