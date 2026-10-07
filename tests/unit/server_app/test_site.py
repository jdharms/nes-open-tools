"""`server/routes/site.py`: the health check, home, the rangefinder, the Markdown pages and ROM setup."""

import re

from golf.randomizer.roms import VANILLA_ROMS
from server.pages import PageCatalog
from tests.unit.server_app.helpers import UNWRITTEN, app_client


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_check_answers_head(client):
    """UptimeRobot's free plan checks with HEAD."""
    response = client.head("/healthz")
    assert response.status_code == 200
    assert response.content == b""


def test_home_links_to_rom_setup_and_generate(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/rom"' in response.text
    assert 'href="/generate"' in response.text
    assert 'href="/rangefinder"' in response.text
    assert "nav.pages" not in response.text


def test_rangefinder_page_embeds_its_assets_and_script_strings(unwritten_client):
    response = unwritten_client.get("/rangefinder")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert re.search(r'href="/rangefinder"\s+aria-current="page"', response.text)
    assert 'data-metadata-url="/rangefinder-data/metadata.json"' in response.text
    assert re.search(
        r'src="/static/rangefinder/app\.js\?v=[0-9a-f]{12}"', response.text
    )
    assert '"rangefinder.script.distance": null' in response.text


def test_rangefinder_generated_assets_are_served(client, rangefinder_assets):
    metadata = client.get("/rangefinder-data/metadata.json")
    image = client.get("/rangefinder-data/images/japan/hole_01.png")
    assert metadata.status_code == 200
    assert metadata.json()["courses"]["japan"]["holes"][0]["width"] == 176
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"


def write_content_page(
    tmp_path, slug: str, metadata: str, body: str = "Page body."
) -> None:
    (tmp_path / f"{slug}.md").write_text(f"+++\n{metadata}\n+++\n\n{body}\n")


def page_catalog(tmp_path, metadata: str, body: str = "Page body.") -> PageCatalog:
    write_content_page(tmp_path, "review-page", metadata, body)
    return PageCatalog.load(tmp_path)


def test_navigation_lists_only_enabled_listed_pages_in_display_order(
    fake_builder, tmp_path
):
    write_content_page(
        tmp_path, "later", 'title = "Later"\nnav_title = "Zed"\norder = 20'
    )
    write_content_page(
        tmp_path, "first", 'title = "First"\nnav_title = "A & B"\norder = 10'
    )
    write_content_page(tmp_path, "review", 'title = "Review"\nlisted = false')
    write_content_page(
        tmp_path, "disabled", 'title = "Disabled"\nenabled = false\nlisted = false'
    )
    pages = PageCatalog.load(tmp_path)
    with app_client(
        builder=fake_builder, pages=pages, strings=UNWRITTEN
    ) as test_client:
        response = test_client.get("/")
    assert response.status_code == 200
    assert "⟦nav.pages⟧" in response.text
    assert response.text.index('href="/pages/first"') < response.text.index(
        'href="/pages/later"'
    )
    assert ">A &amp; B</a>" in response.text
    assert 'href="/pages/review"' not in response.text
    assert 'href="/pages/disabled"' not in response.text


def test_content_page_marks_its_dropdown_and_link_current(fake_builder, tmp_path):
    pages = page_catalog(tmp_path, 'title = "Review"')
    with app_client(builder=fake_builder, pages=pages) as test_client:
        response = test_client.get("/pages/review-page")
    assert response.status_code == 200
    assert '<summary aria-current="page">' in response.text
    assert re.search(
        r'<a href="/pages/review-page"\s+aria-current="page">Review</a>', response.text
    )


def test_markdown_page_is_served_with_its_title_and_body(fake_builder, tmp_path):
    pages = page_catalog(
        tmp_path, 'title = "Review & Notes"', "A **rendered** paragraph."
    )
    with app_client(builder=fake_builder, pages=pages) as test_client:
        response = test_client.get("/pages/review-page")
    assert response.status_code == 200
    assert "<title>Review &amp; Notes — NES Open Randomizer</title>" in response.text
    assert "<h1>Review &amp; Notes</h1>" in response.text
    assert "<p>A <strong>rendered</strong> paragraph.</p>" in response.text
    assert 'name="robots"' not in response.text


def test_unlisted_markdown_page_is_served_with_noindex(fake_builder, tmp_path):
    pages = page_catalog(tmp_path, 'title = "Review"\nlisted = false')
    with app_client(builder=fake_builder, pages=pages) as test_client:
        response = test_client.get("/pages/review-page")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex, nofollow">' in response.text
    assert 'href="/pages/review-page"' not in response.text


def test_disabled_and_unknown_markdown_pages_are_not_found(fake_builder, tmp_path):
    pages = page_catalog(
        tmp_path, 'title = "Disabled"\nenabled = false\nlisted = false'
    )
    with app_client(builder=fake_builder, pages=pages) as test_client:
        disabled = test_client.get("/pages/review-page")
        unknown = test_client.get("/pages/missing")
    assert disabled.status_code == 404
    assert unknown.status_code == 404
    assert "Disabled" not in disabled.text


def collection_catalog(tmp_path) -> PageCatalog:
    collection = tmp_path / "updates"
    collection.mkdir()
    (collection / "_index.md").write_text('+++\ntitle = "Updates"\n+++\n\nIntro.\n')
    for name, metadata in [
        ("older", 'title = "Older"\ndate = 2026-01-02'),
        ("newer", 'title = "Newer & Better"\ndate = 2026-10-01'),
        ("draft", 'title = "Draft"\ndate = 2026-11-01\nenabled = false'),
    ]:
        (collection / f"{name}.md").write_text(
            f"+++\n{metadata}\n+++\n\nBody of {name}.\n"
        )
    return PageCatalog.load(tmp_path)


def test_collection_page_shows_its_entries_as_linked_cards(fake_builder, tmp_path):
    pages = collection_catalog(tmp_path)
    with app_client(builder=fake_builder, pages=pages) as test_client:
        home = test_client.get("/")
        response = test_client.get("/pages/updates")
    assert 'href="/pages/updates"' in home.text
    assert response.status_code == 200
    assert "<title>Updates — NES Open Randomizer</title>" in response.text
    assert "<h1>Updates</h1>" in response.text
    assert '<article class="content-page">' not in response.text
    assert response.text.index("<p>Intro.</p>") < response.text.index('id="newer"')
    assert response.text.index('id="newer"') < response.text.index('id="older"')
    assert re.search(
        r'<article id="newer" class="entry">\s*<header>\s*<h2>\s*'
        r'<a href="#newer">Newer &amp; Better</a>\s*</h2>\s*'
        r'<time datetime="2026-10-01">2026-10-01</time>\s*</header>\s*'
        r"<p>Body of newer.</p>",
        response.text,
    )
    assert "Draft" not in response.text
    assert "Body of draft" not in response.text


def test_rom_setup_lists_every_vanilla_rom_with_its_hash(client):
    response = client.get("/rom")
    assert response.status_code == 200
    for rom in VANILLA_ROMS:
        assert f'data-rom-id="{rom.id}"' in response.text
        assert f'data-sha1="{rom.sha1}"' in response.text
        assert rom.title in response.text
    assert response.text.count('data-state="checking"') == len(VANILLA_ROMS)
    assert 'id="rom-strings"' in response.text
    assert response.text.index('src="/static/romstore.js?v=') < response.text.index(
        'src="/static/rom.js?v='
    )
