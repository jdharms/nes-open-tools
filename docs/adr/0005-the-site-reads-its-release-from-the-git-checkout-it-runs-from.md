+++
status = "accepted"
date = 2026-09-23
area = "site"
permanent = false
revisit_when = "The site is deployed some other way than a git checkout of its release tag, such as a container image or a built package"
drafted_by = "Claude"
supersedes = []
+++

# The site reads its release from the git checkout it runs from

## Context

The site's footer shows which release is running. Releases are marked by `server-v*`
tags (`server-v1.0.2`), and the footer shows the part after `server-`. Nobody should
have to edit a version file before tagging a release. `deploy/deploy.sh` deploys by
checking the release tag out in `/opt/golf-site`, so the running checkout already
names its own release.

## Decision

At startup, `create_app` runs `git describe --tags --match 'server-v*' --dirty` in the
checkout (`server/version.py`) and shows the result, without the `server-` prefix, at the
right of the site footer on every page, admin pages included. A deployed release reads
`v1.0.2`. A development checkout reads how far it is past the last release, its commit
and whether tracked files have changed, such as `v1.0.2-10-gc66d426-dirty`:

> working in development is a great value add to the feature.

The service runs as `golf` but the checkout belongs to the deploy user, which git
refuses to read by default, so the command names the checkout `safe.directory`. If git
fails, the footer shows no version and the site runs as normal.

## Rejected alternatives

- **`deploy.sh` writes the tag to a gitignored file the app reads.** This avoids the
  ownership setting, but development still needs `git describe`, so there would be two
  paths. The first deploy that added the step also wouldn't write the file, because
  `deploy.sh` runs the copy of itself from before the checkout.
- **Build the version into the package metadata (`setuptools-scm`, `hatch-vcs`).** The
  repository holds two artifacts, the site and the course editor, so one package version
  can't describe both. An editable install's version also goes stale until `uv sync` runs
  again.
- **A version file edited before each release.** This is the manual step the feature
  exists to avoid.

## Consequences

- The server needs git installed and a readable `.git` in the checkout at runtime, not
  only at deploy time. Both are already there.
- Rolling back shows the older release with no extra step.
- A release tag must be reachable from the deployed commit, which is true of any
  deploy made with `deploy.sh`.
- Tests pass `version=` to `create_app` to fix what the footer shows.

## Sources

- `server/version.py`, `deploy/deploy.sh`, `docs/deployment.md`
- Claude Code session: 2026-09-23 `f942452b` (the footer version, and showing
  development builds)
