"""A player's saved download settings: the cookie, the account's copy, and `/me`'s form for them."""

import re

import pytest
from fastapi.testclient import TestClient

from golf.core.patches.extended_sram_defaults import BallSpin, SwingSpeed
from golf.core.patches.sram_defaults import Club
from server.app import create_app
from server.config import Config
from server.download_settings import load_settings
from server.forms import SavedSettings
from server.routes.common import DOWNLOAD_COOKIE
from tests.app_state import app_state
from tests.unit.server_app.helpers import (
    dev_client,
    download_article,
    generate_seed,
    post_download,
    seed_form,
    summary_values,
    users,
)


def download_cookie(response) -> str:
    [header] = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{DOWNLOAD_COOKIE}=")
    ]
    return header


def saved_in(client: TestClient) -> SavedSettings:
    return SavedSettings.from_cookie(client.cookies.get(DOWNLOAD_COOKIE))


def test_a_download_saves_the_settings_in_a_long_lived_cookie(client):
    seed_id = generate_seed(client)
    extra = {"bgm": ["off"], "swing": "fast", "spin": "back1"}
    response = post_download(client, seed_id, name="luigi", extra=extra)
    header = download_cookie(response)
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert f"Max-Age={365 * 24 * 60 * 60}" in header
    assert "Path=/" in header
    assert "Secure" not in header
    assert saved_in(client) == SavedSettings(
        player_name="LUIGI",
        clubs=frozenset({Club.W1, Club.PW, Club.PT}),
        bgm=False,
        swing=SwingSpeed.FAST,
        putt=SwingSpeed.OFF,
        spin=BallSpin.BACK1,
    )


def test_the_cookie_is_secure_on_an_https_site(fake_builder):
    config = Config(database=":memory:", base_url="https://golf.example")
    with TestClient(create_app(config, builder=fake_builder)) as test_client:
        response = post_download(test_client, generate_seed(test_client))
    assert "Secure" in download_cookie(response)


def test_a_refused_download_saves_nothing(client):
    seed_id = generate_seed(client)
    response = post_download(client, seed_id, name="LU1GI")
    assert response.status_code == 400
    assert DOWNLOAD_COOKIE not in response.headers.get("set-cookie", "")


def test_a_later_seed_page_starts_from_the_saved_settings(client):
    post_download(
        client,
        generate_seed(client),
        name="luigi",
        clubs=("1W", "3W", "PW"),
        extra={"bgm": ["off"], "putt": "medium"},
    )
    article = download_article(client.get(f"/h/{generate_seed(client)}").text)
    assert re.search(r'name="player_name"\s+value="LUIGI"', article)
    assert re.findall(r'name="clubs"\s+value="(\w+)"\s+checked', article) == [
        "1W",
        "3W",
        "PW",
    ]
    assert not re.search(r'name="bgm"\s+value="on"\s+role="switch"\s+checked', article)
    assert re.search(r'<option value="medium"\s+selected>', article)


def test_a_restricted_seed_keeps_the_saved_bag(client):
    post_download(client, generate_seed(client), clubs=("1W", "3W", "SW"))
    strict = generate_seed(client, seed_form(banned={"SW"}))
    post_download(client, strict, name="toad", clubs=("1W", "PW"))
    saved = saved_in(client)
    assert saved.player_name == "TOAD"
    assert saved.clubs == {Club.W1, Club.W3, Club.SW, Club.PT}


@pytest.mark.parametrize("value", ["garbage", "!!!", "e30", "eyJ2IjoxfQ"])
def test_a_cookie_that_does_not_decode_starts_the_form_from_vanilla(client, value):
    client.cookies.set(DOWNLOAD_COOKIE, value)
    article = download_article(client.get(f"/h/{generate_seed(client)}").text)
    assert re.search(r'name="player_name"\s+value="MARIO"', article)
    assert summary_values(article)["clubs"] == ["14", "14"]


def test_a_garbage_cookie_is_replaced_by_the_next_download(client):
    client.cookies.set(DOWNLOAD_COOKIE, "garbage")
    response = post_download(client, generate_seed(client), name="luigi")
    value = download_cookie(response).split(";")[0].split("=", 1)[1]
    assert SavedSettings.from_cookie(value).player_name == "LUIGI"


def test_a_signed_in_players_entry_names_the_seed_page_over_the_cookie(fake_builder):
    with dev_client(fake_builder) as test_client:
        seed_id = generate_seed(test_client)
        test_client.get("/auth/login", params={"as": "alice"})
        post_download(test_client, seed_id, name="yoshi", clubs=("2W", "PW"))
        other = generate_seed(test_client)
        post_download(
            test_client, other, name="luigi", clubs=("1W",), extra={"swing": "slow"}
        )

        first = download_article(test_client.get(f"/h/{seed_id}").text)
        assert re.search(r'name="player_name"\s+value="YOSHI"', first)
        assert re.findall(r'name="clubs"\s+value="(\w+)"\s+checked', first) == [
            "2W",
            "PW",
        ]
        assert re.search(r'<option value="slow"\s+selected>', first)

        fresh = download_article(
            test_client.get(f"/h/{generate_seed(test_client)}").text
        )
        assert re.search(r'name="player_name"\s+value="LUIGI"', fresh)


def account_settings(client: TestClient, name: str = "alice") -> SavedSettings | None:
    [row] = [u for u in users(client) if u["discord_id"] == f"dev:{name}"]
    return load_settings(app_state(client).db, row["id"])


def test_a_signed_in_download_saves_to_the_account_too(fake_builder):
    with dev_client(fake_builder) as test_client:
        seed_id = generate_seed(test_client)
        test_client.get("/auth/login", params={"as": "alice"})
        post_download(test_client, seed_id, name="luigi", extra={"swing": "fast"})
        saved = account_settings(test_client)
        assert saved is not None
        assert (saved.player_name, saved.swing) == ("LUIGI", SwingSpeed.FAST)
        assert saved_in(test_client) == saved


def test_a_signed_in_player_starts_from_the_cookie_until_they_save(fake_builder):
    with dev_client(fake_builder) as test_client:
        post_download(test_client, generate_seed(test_client), name="guest")
        test_client.get("/auth/login", params={"as": "alice"})
        assert account_settings(test_client) is None
        page = test_client.get(f"/h/{generate_seed(test_client)}").text
        assert re.search(r'name="player_name"\s+value="GUEST"', page)


def test_the_account_wins_over_this_browsers_cookie(fake_builder):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        post_download(test_client, generate_seed(test_client), name="alice")
        test_client.cookies.set(
            DOWNLOAD_COOKIE, SavedSettings(player_name="BOB").to_cookie()
        )
        page = test_client.get(f"/h/{generate_seed(test_client)}").text
        assert re.search(r'name="player_name"\s+value="ALICE"', page)


def test_the_account_keeps_its_bag_through_a_restricted_seed(fake_builder):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        post_download(test_client, generate_seed(test_client), clubs=("1W", "SW"))
        strict = generate_seed(test_client, seed_form(banned={"SW"}))
        post_download(test_client, strict, name="toad", clubs=("PW",))
        saved = account_settings(test_client)
        assert saved is not None
        assert saved.player_name == "TOAD"
        assert saved.clubs == {Club.W1, Club.SW, Club.PT}


def me_form(**changes) -> dict:
    data = {
        "player_name": "yoshi",
        "clubs": ["2W", "PW"],
        "bgm": ["off"],
        "swing": "medium",
        "putt": "slow",
        "spin": "top1",
    }
    return data | changes


def test_me_shows_the_saved_settings_form(fake_builder):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        page = test_client.get("/me").text
        section = page[page.index('<section id="download-settings">') :]
        assert 'action="/me/download-settings"' in section
        assert re.search(r'name="player_name"\s+value="MARIO"', section)
        assert section.count('name="clubs"') == 15
        assert "disabled" not in section
        for field in ("swing", "putt", "spin"):
            assert f'<select name="{field}">' in section
        assert "/me/download-settings/forget" not in section


def test_saving_on_me_stores_the_settings_and_redirects_back(fake_builder):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        response = test_client.post(
            "/me/download-settings", data=me_form(), follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/me?result=saved#download-settings"
        expected = SavedSettings(
            player_name="YOSHI",
            clubs=frozenset({Club.W2, Club.PW, Club.PT}),
            bgm=False,
            swing=SwingSpeed.MEDIUM,
            putt=SwingSpeed.SLOW,
            spin=BallSpin.TOP1,
        )
        assert account_settings(test_client) == expected
        assert saved_in(test_client) == expected
        page = test_client.get("/me").text
        assert re.search(r'name="player_name"\s+value="YOSHI"', page)
        assert "/me/download-settings/forget" in page


@pytest.mark.parametrize(
    "changes, result",
    [
        ({"player_name": "LU1GI"}, "invalid_name"),
        (
            {"clubs": [club.label for club in Club if club != Club.PT]},
            "clubs_over_max",
        ),
        ({"spin": "sideways"}, "invalid"),
    ],
)
def test_settings_me_cannot_save_are_refused_and_nothing_changes(
    fake_builder, changes, result
):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        response = test_client.post(
            "/me/download-settings", data=me_form(**changes), follow_redirects=False
        )
        assert response.status_code == 400
        section = response.text[
            response.text.index('<section id="download-settings">') :
        ]
        assert "<del>" in section
        assert re.search(
            rf'name="player_name"\s+value="{changes.get("player_name", "yoshi")}"',
            section,
            flags=re.IGNORECASE,
        )
        expected_clubs = changes.get("clubs", ["2W", "PW"])
        assert (
            re.findall(r'name="clubs"\s+value="(\w+)"\s+checked', section)
            == expected_clubs
        )
        assert re.search(r'<option value="medium"\s+selected>', section)
        assert re.search(r'<option value="slow"\s+selected>', section)
        assert account_settings(test_client) is None
        assert DOWNLOAD_COOKIE not in response.headers.get("set-cookie", "")


def test_forgetting_deletes_the_row_and_expires_the_cookie(fake_builder):
    with dev_client(fake_builder) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        test_client.post("/me/download-settings", data=me_form())
        response = test_client.post(
            "/me/download-settings/forget", follow_redirects=False
        )
        assert response.headers["location"] == "/me?result=forgotten#download-settings"
        header = download_cookie(response)
        assert "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header
        assert account_settings(test_client) is None
        assert DOWNLOAD_COOKIE not in test_client.cookies
        page = test_client.get(f"/h/{generate_seed(test_client)}").text
        assert re.search(r'name="player_name"\s+value="MARIO"', page)


def test_signed_out_the_settings_routes_are_not_found(client):
    assert client.post("/me/download-settings", data=me_form()).status_code == 404
    assert client.post("/me/download-settings/forget").status_code == 404
