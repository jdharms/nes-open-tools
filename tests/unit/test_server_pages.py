"""Loading, validating, and rendering the site's checked-in Markdown pages."""

from datetime import date
from pathlib import Path

import pytest
from markupsafe import Markup

from server.pages import PageCatalog, PageError


def write_page(
    directory: Path, name: str, frontmatter: str, body: str = "Body."
) -> None:
    (directory / name).write_text(f"+++\n{frontmatter}\n+++\n\n{body}\n")


def test_an_empty_directory_is_an_empty_catalog(tmp_path):
    catalog = PageCatalog.load(tmp_path)
    assert catalog.pages == ()
    assert catalog.listed == ()


def test_a_page_uses_its_filename_and_metadata_defaults(tmp_path):
    write_page(tmp_path, "playing-guide.md", 'title = "  Playing Guide  "')
    page = PageCatalog.load(tmp_path).pages[0]
    assert page.slug == "playing-guide"
    assert page.title == "Playing Guide"
    assert page.nav_title == "Playing Guide"
    assert page.order == 100
    assert page.enabled
    assert page.listed
    assert isinstance(page.body_html, Markup)
    assert page.body_html == "<p>Body.</p>\n"


def test_explicit_metadata_and_markdown_features(tmp_path):
    write_page(
        tmp_path,
        "reference.md",
        "\n".join(
            [
                'title = "Reference"',
                'nav_title = "Short"',
                "order = 12",
                "enabled = true",
                "listed = false",
            ]
        ),
        "## Section\n\n| A | B |\n| - | - |\n| 1 | 2 |",
    )
    page = PageCatalog.load(tmp_path).pages[0]
    assert (page.nav_title, page.order, page.enabled, page.listed) == (
        "Short",
        12,
        True,
        False,
    )
    assert "<h2>Section</h2>" in page.body_html
    assert "<table>" in page.body_html


def test_raw_html_is_not_rendered(tmp_path):
    write_page(tmp_path, "safe.md", 'title = "Safe"', '<script>alert("x")</script>')
    html = PageCatalog.load(tmp_path).pages[0].body_html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_listed_pages_are_enabled_and_sorted_for_display(tmp_path):
    write_page(tmp_path, "zulu.md", 'title = "Zulu"\norder = 1')
    write_page(tmp_path, "alpha.md", 'title = "Alpha"\norder = 1')
    write_page(tmp_path, "later.md", 'title = "Later"\norder = 2')
    write_page(tmp_path, "unlisted.md", 'title = "Unlisted"\nlisted = false')
    write_page(
        tmp_path, "disabled.md", 'title = "Disabled"\nenabled = false\nlisted = false'
    )
    catalog = PageCatalog.load(tmp_path)
    assert [page.slug for page in catalog.listed] == ["alpha", "zulu", "later"]
    unlisted = catalog.get("unlisted")
    assert unlisted is not None
    assert unlisted.slug == "unlisted"
    assert catalog.get("disabled") is None
    assert catalog.get("missing") is None


@pytest.mark.parametrize(
    ("name", "source", "problem"),
    [
        ("bad.md", "Body only", "first line"),
        ("bad.md", '+++\ntitle = "Bad"\n', "missing closing"),
        ("bad.md", "+++\ntitle = [\n+++\n", "invalid TOML"),
        ("bad.md", "+++\norder = 1\n+++\n", "title must be a nonempty string"),
        ("bad.md", '+++\ntitle = " "\n+++\n', "title must be a nonempty string"),
        ("bad.md", '+++\ntitle = "Bad"\nunknown = 1\n+++\n', "unknown frontmatter"),
        (
            "bad.md",
            '+++\ntitle = "Bad"\nnav_title = 1\n+++\n',
            "nav_title must be a nonempty string",
        ),
        (
            "bad.md",
            '+++\ntitle = "Bad"\norder = true\n+++\n',
            "order must be an integer",
        ),
        (
            "bad.md",
            '+++\ntitle = "Bad"\nenabled = 1\n+++\n',
            "enabled must be a boolean",
        ),
        ("bad.md", '+++\ntitle = "Bad"\nlisted = 1\n+++\n', "listed must be a boolean"),
        (
            "bad.md",
            '+++\ntitle = "Bad"\nenabled = false\nlisted = true\n+++\n',
            "disabled page cannot be listed",
        ),
    ],
)
def test_malformed_pages_name_the_file(tmp_path, name, source, problem):
    (tmp_path / name).write_text(source)
    with pytest.raises(PageError, match=problem) as caught:
        PageCatalog.load(tmp_path)
    assert name in str(caught.value)


def test_invalid_filename_is_rejected(tmp_path):
    write_page(tmp_path, "Bad_Name.md", 'title = "Bad"')
    with pytest.raises(PageError, match="Bad_Name.md.*filename"):
        PageCatalog.load(tmp_path)


def write_collection(directory: Path, name: str = "updates", intro: str = "") -> Path:
    collection = directory / name
    collection.mkdir()
    write_page(collection, "_index.md", 'title = "Updates"', intro)
    return collection


def test_a_directory_is_a_collection_with_its_index_metadata(tmp_path):
    collection = write_collection(tmp_path, intro="An *intro*.")
    write_page(collection, "first.md", 'title = "First"\ndate = 2026-10-01', "Hi.")
    page = PageCatalog.load(tmp_path).pages[0]
    assert page.slug == "updates"
    assert page.title == "Updates"
    assert page.collection
    assert page.body_html == "<p>An <em>intro</em>.</p>\n"
    [entry] = page.entries
    assert entry.slug == "first"
    assert entry.title == "First"
    assert entry.date == date(2026, 10, 1)
    assert isinstance(entry.body_html, Markup)
    assert entry.body_html == "<p>Hi.</p>\n"


def test_a_page_file_is_not_a_collection(tmp_path):
    write_page(tmp_path, "plain.md", 'title = "Plain"')
    page = PageCatalog.load(tmp_path).pages[0]
    assert not page.collection
    assert page.entries == ()


def test_a_collection_with_only_its_index_has_no_entries(tmp_path):
    write_collection(tmp_path)
    page = PageCatalog.load(tmp_path).pages[0]
    assert page.collection
    assert page.entries == ()


def test_entries_are_newest_first_with_ties_broken_by_filename(tmp_path):
    collection = write_collection(tmp_path)
    write_page(collection, "v1-0-0.md", 'title = "A"\ndate = 2026-01-01')
    write_page(collection, "v3-0-0.md", 'title = "B"\ndate = 2026-10-01')
    write_page(collection, "v3-0-1.md", 'title = "C"\ndate = 2026-10-01')
    write_page(collection, "v2-0-0.md", 'title = "D"\ndate = 2026-05-01')
    page = PageCatalog.load(tmp_path).pages[0]
    assert [entry.slug for entry in page.entries] == [
        "v3-0-1",
        "v3-0-0",
        "v2-0-0",
        "v1-0-0",
    ]


def test_disabled_entries_are_dropped(tmp_path):
    collection = write_collection(tmp_path)
    write_page(collection, "shown.md", 'title = "Shown"\ndate = 2026-01-01')
    write_page(
        collection,
        "draft.md",
        'title = "Draft"\ndate = 2026-02-01\nenabled = false',
    )
    page = PageCatalog.load(tmp_path).pages[0]
    assert [entry.slug for entry in page.entries] == ["shown"]


def test_a_disabled_entry_is_still_validated(tmp_path):
    collection = write_collection(tmp_path)
    write_page(collection, "draft.md", 'title = "Draft"\nenabled = false')
    with pytest.raises(PageError, match="updates/draft.md: date"):
        PageCatalog.load(tmp_path)


def test_raw_html_is_not_rendered_in_entries(tmp_path):
    collection = write_collection(tmp_path)
    write_page(
        collection,
        "entry.md",
        'title = "Entry"\ndate = 2026-01-01',
        "<script>alert(1)</script>",
    )
    html = PageCatalog.load(tmp_path).pages[0].entries[0].body_html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_collection_index_metadata_is_validated_like_a_page(tmp_path):
    collection = tmp_path / "updates"
    collection.mkdir()
    write_page(collection, "_index.md", 'title = "Updates"\norder = "1"')
    with pytest.raises(PageError, match="updates/_index.md: order must be an integer"):
        PageCatalog.load(tmp_path)


def test_non_markdown_files_in_a_collection_are_ignored(tmp_path):
    collection = write_collection(tmp_path)
    (collection / "notes.txt").write_text("not an entry")
    assert PageCatalog.load(tmp_path).pages[0].entries == ()


@pytest.mark.parametrize(
    ("name", "source", "problem"),
    [
        ("entry.md", "date = 2026-01-01", "title must be a nonempty string"),
        ("entry.md", 'title = "Entry"', "date must be a TOML date"),
        (
            "entry.md",
            'title = "Entry"\ndate = "2026-01-01"',
            "date must be a TOML date",
        ),
        (
            "entry.md",
            'title = "Entry"\ndate = 2026-01-01T12:00:00',
            "date must be a TOML date",
        ),
        (
            "entry.md",
            'title = "Entry"\ndate = 2026-01-01\nenabled = 1',
            "enabled must be a boolean",
        ),
        (
            "entry.md",
            'title = "Entry"\ndate = 2026-01-01\norder = 1',
            "unknown frontmatter",
        ),
        ("Bad_Entry.md", 'title = "Entry"\ndate = 2026-01-01', "filename"),
        ("_draft.md", 'title = "Entry"\ndate = 2026-01-01', "filename"),
    ],
)
def test_malformed_entries_name_the_file(tmp_path, name, source, problem):
    collection = write_collection(tmp_path)
    write_page(collection, name, source)
    with pytest.raises(PageError, match=problem) as caught:
        PageCatalog.load(tmp_path)
    assert f"updates/{name}" in str(caught.value)


def test_a_collection_needs_an_index(tmp_path):
    collection = tmp_path / "updates"
    collection.mkdir()
    write_page(collection, "entry.md", 'title = "Entry"\ndate = 2026-01-01')
    with pytest.raises(PageError, match="updates: a collection needs _index.md"):
        PageCatalog.load(tmp_path)


def test_an_invalid_collection_directory_name_is_rejected(tmp_path):
    write_collection(tmp_path, "Bad_Name")
    with pytest.raises(PageError, match="Bad_Name: directory name"):
        PageCatalog.load(tmp_path)


def test_directories_inside_a_collection_are_rejected(tmp_path):
    collection = write_collection(tmp_path)
    (collection / "nested").mkdir()
    with pytest.raises(PageError, match="updates/nested: collections cannot contain"):
        PageCatalog.load(tmp_path)


def test_a_page_file_and_collection_cannot_share_a_slug(tmp_path):
    write_collection(tmp_path)
    write_page(tmp_path, "updates.md", 'title = "Updates"')
    with pytest.raises(PageError, match=r"named \['updates'\]"):
        PageCatalog.load(tmp_path)


def test_a_disabled_collection_is_absent(tmp_path):
    collection = tmp_path / "updates"
    collection.mkdir()
    write_page(
        collection, "_index.md", 'title = "Updates"\nenabled = false\nlisted = false'
    )
    catalog = PageCatalog.load(tmp_path)
    assert catalog.get("updates") is None
    assert catalog.listed == ()


def test_the_checked_in_pages_load():
    PageCatalog.load()


def test_missing_directory_is_rejected(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(PageError, match="directory does not exist"):
        PageCatalog.load(missing)
