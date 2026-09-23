"""The site's release, read from a git checkout (server/version.py)."""

import subprocess
from pathlib import Path

import pytest

from server.version import site_version


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet")
    (tmp_path / "file.txt").write_text("one\n")
    git(tmp_path, "add", "file.txt")
    git(tmp_path, "commit", "--quiet", "-m", "one")
    return tmp_path


def commit(repo: Path, text: str) -> str:
    (repo / "file.txt").write_text(text)
    git(repo, "commit", "--quiet", "-am", text)
    return git(repo, "rev-parse", "--short", "HEAD")


def test_a_checkout_on_a_release_tag_is_that_release(repo):
    git(repo, "tag", "server-v1.2.3")
    assert site_version(repo) == "v1.2.3"


def test_a_checkout_past_a_release_names_the_distance_and_commit(repo):
    git(repo, "tag", "server-v1.2.3")
    head = commit(repo, "two")
    assert site_version(repo) == f"v1.2.3-1-g{head}"


def test_changed_tracked_files_mark_the_version_dirty(repo):
    git(repo, "tag", "server-v1.2.3")
    (repo / "file.txt").write_text("changed\n")
    (repo / "untracked.txt").write_text("not counted\n")
    assert site_version(repo) == "v1.2.3-dirty"


def test_other_artifacts_tags_are_ignored(repo):
    git(repo, "tag", "server-v1.2.3")
    commit(repo, "two")
    git(repo, "tag", "editor-v2.0.0")
    version = site_version(repo)
    assert version is not None and version.startswith("v1.2.3-1-g")


def test_no_release_tag_or_no_repository_is_no_version(repo, tmp_path_factory):
    assert site_version(repo) is None
    assert site_version(tmp_path_factory.mktemp("not_a_repo")) is None
