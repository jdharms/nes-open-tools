"""`server/routes/account.py`: signing in and out, and `/me`."""

import logging
import re
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from server.app import SESSION_COOKIE, create_app
from server.auth import DiscordClient, DiscordError, DiscordIdentity
from server.config import Config, ConfigError
from tests.app_state import app_state
from tests.unit.server_app.helpers import (
    UNWRITTEN,
    dev_client,
    entered_seed,
    generate_seed,
    post_download,
    scan_path,
    users,
)

DISCORD_CONFIG = Config(
    database=":memory:",
    discord_client_id="client-id",
    discord_client_secret="client-secret",
    session_secret="s",
)


NELLY = DiscordIdentity("80351110224678912", "nelly", "Nelly", "abc123")


class FakeDiscord(DiscordClient):
    """Answers every code with `identity`, or raises DiscordError when there is none."""

    def __init__(self, identity: DiscordIdentity | None = NELLY):
        super().__init__("client-id", "client-secret")
        self.identity = identity
        self.codes: list[tuple[str, str]] = []

    async def identify(self, code, redirect_uri):
        self.codes.append((code, redirect_uri))
        if self.identity is None:
            raise DiscordError("down")
        return self.identity


def start_discord_sign_in(client: TestClient, next_path: str = "/generate") -> str:
    """Begin a Discord sign-in and return the state it sent Discord."""
    response = client.get(
        "/auth/login", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return query["state"][0]


def test_sign_in_is_hidden_and_missing_when_not_configured(unwritten_client):
    assert "nav.sign_in" not in unwritten_client.get("/").text
    assert unwritten_client.get("/auth/login").status_code == 404
    assert (
        unwritten_client.get(
            "/auth/callback", params={"state": "x", "code": "y"}
        ).status_code
        == 404
    )


def test_the_bypass_signs_in_as_the_named_user(fake_builder):
    with dev_client(fake_builder, strings=UNWRITTEN) as test_client:
        assert "⟦nav.sign_in⟧" in test_client.get("/generate").text
        response = test_client.get(
            "/auth/login",
            params={"as": "alice", "next": "/generate"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/generate"
        page = test_client.get("/generate").text
        assert "⟦nav.signed_in_as name=alice⟧" in page
        assert "nav.sign_in⟧" not in page
        [alice] = users(test_client)
        assert (alice["discord_id"], alice["username"], alice["global_name"]) == (
            "dev:alice",
            "alice",
            None,
        )
        assert 1 <= alice["player_id"] <= 4294967295


def test_the_bypass_without_a_name_signs_in_as_dev(fake_builder):
    with dev_client(fake_builder) as test_client:
        assert (
            test_client.get("/auth/login", follow_redirects=False).headers["location"]
            == "/"
        )
        assert [user["discord_id"] for user in users(test_client)] == ["dev:dev"]


@pytest.mark.parametrize("name", ["", "a b", "x" * 33, "dev:alice"])
def test_the_bypass_refuses_odd_names(fake_builder, name):
    with dev_client(fake_builder) as test_client:
        assert test_client.get("/auth/login", params={"as": name}).status_code == 400
        assert users(test_client) == []


def test_the_bypass_is_refused_off_localhost(fake_builder):
    with pytest.raises(ConfigError):
        create_app(
            Config(
                database=":memory:", dev_login=True, base_url="https://golf.example"
            ),
            builder=fake_builder,
        )


def test_signing_out_clears_the_session_and_returns(fake_builder):
    with dev_client(fake_builder, strings=UNWRITTEN) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        page = test_client.get("/rom").text
        assert '<input type="hidden" name="next" value="/rom">' in page
        response = test_client.post(
            "/auth/logout", data={"next": "/rom"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/rom"
        assert "⟦nav.sign_in⟧" in test_client.get("/rom").text


def test_the_sign_in_link_returns_to_the_current_page(fake_builder):
    with dev_client(fake_builder) as test_client:
        assert (
            'href="/auth/login?next=/generate%3Fpar%3D71"'
            in test_client.get("/generate?par=71").text
        )


@pytest.mark.parametrize("next_path", ["https://evil.example/", "//evil.example/"])
def test_sign_in_never_returns_off_site(fake_builder, next_path):
    with dev_client(fake_builder) as test_client:
        response = test_client.get(
            "/auth/login",
            params={"as": "alice", "next": next_path},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/"
        response = test_client.post(
            "/auth/logout", data={"next": next_path}, follow_redirects=False
        )
        assert response.headers["location"] == "/"


def test_a_session_for_a_missing_user_is_signed_out(fake_builder):
    with dev_client(fake_builder, strings=UNWRITTEN) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        with app_state(test_client).db.transaction() as conn:
            conn.execute("DELETE FROM users")
        assert "⟦nav.sign_in⟧" in test_client.get("/").text


def test_the_session_cookie_is_lax_and_secure_only_on_https(fake_builder):
    with dev_client(fake_builder) as test_client:
        cookie = test_client.get(
            "/auth/login", params={"as": "alice"}, follow_redirects=False
        ).headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "samesite=lax" in cookie.lower()
    assert "secure" not in cookie.lower()
    https = replace(DISCORD_CONFIG, base_url="https://golf.example")
    with TestClient(
        create_app(https, builder=fake_builder, discord=FakeDiscord()),
        base_url="https://golf.example",
    ) as test_client:
        cookie = test_client.get("/auth/login", follow_redirects=False).headers[
            "set-cookie"
        ]
    assert "secure" in cookie.lower()


def test_discord_sign_in_redirects_to_discord_with_a_state(fake_builder):
    with TestClient(create_app(DISCORD_CONFIG, builder=fake_builder)) as test_client:
        response = test_client.get("/auth/login", follow_redirects=False)
    location = urlsplit(response.headers["location"])
    assert (
        f"{location.scheme}://{location.netloc}{location.path}"
        == "https://discord.com/oauth2/authorize"
    )
    query = parse_qs(location.query)
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/auth/callback"]
    assert len(query["state"][0]) >= 32


def test_discord_sign_in_records_the_user_and_returns(fake_builder):
    discord = FakeDiscord()
    with TestClient(
        create_app(
            DISCORD_CONFIG, strings=UNWRITTEN, builder=fake_builder, discord=discord
        )
    ) as test_client:
        state = start_discord_sign_in(test_client)
        response = test_client.get(
            "/auth/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/generate"
        assert discord.codes == [("abc", "http://127.0.0.1:8000/auth/callback")]
        assert "⟦nav.signed_in_as name=Nelly⟧" in test_client.get("/").text
        [nelly] = users(test_client)
        assert (
            nelly["discord_id"],
            nelly["username"],
            nelly["global_name"],
            nelly["avatar"],
        ) == (
            "80351110224678912",
            "nelly",
            "Nelly",
            "abc123",
        )
        # The state is spent: replaying the callback does not sign in again.
        replay = test_client.get(
            "/auth/callback", params={"code": "abc", "state": state}
        )
        assert replay.status_code == 400
        assert "⟦sign_in_failed.expired⟧" in replay.text


@pytest.mark.parametrize("params", [{"code": "abc", "state": "wrong"}, {"code": "abc"}])
def test_a_callback_whose_state_does_not_match_is_refused(fake_builder, params):
    discord = FakeDiscord()
    with TestClient(
        create_app(
            DISCORD_CONFIG, strings=UNWRITTEN, builder=fake_builder, discord=discord
        )
    ) as test_client:
        start_discord_sign_in(test_client)
        response = test_client.get("/auth/callback", params=params)
        assert response.status_code == 400
        assert "⟦sign_in_failed.expired⟧" in response.text
        assert "sign_in_failed.unavailable" not in response.text
        assert discord.codes == []
        assert users(test_client) == []


def test_turning_discord_down_returns_signed_out(fake_builder):
    discord = FakeDiscord()
    with TestClient(
        create_app(
            DISCORD_CONFIG, strings=UNWRITTEN, builder=fake_builder, discord=discord
        )
    ) as test_client:
        state = start_discord_sign_in(test_client, "/rom")
        response = test_client.get(
            "/auth/callback",
            params={"error": "access_denied", "state": state},
            follow_redirects=False,
        )
        assert response.headers["location"] == "/rom"
        assert discord.codes == []
        assert "⟦nav.sign_in⟧" in test_client.get("/rom").text


def test_discord_failing_shows_unavailable(fake_builder):
    with TestClient(
        create_app(
            DISCORD_CONFIG,
            strings=UNWRITTEN,
            builder=fake_builder,
            discord=FakeDiscord(None),
        )
    ) as test_client:
        state = start_discord_sign_in(test_client)
        response = test_client.get(
            "/auth/callback", params={"code": "abc", "state": state}
        )
        assert response.status_code == 502
        assert "⟦sign_in_failed.unavailable⟧" in response.text
        assert 'href="/auth/login?next=/"' in response.text
        assert users(test_client) == []


def test_my_page_needs_sign_in(fake_builder, client):
    with dev_client(fake_builder) as test_client:
        response = test_client.get("/me", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/auth/login?next=/me"
    assert client.get("/me").status_code == 404


def test_my_page_lists_only_my_entries_newest_first(fake_builder):
    with dev_client(fake_builder, strings=UNWRITTEN) as test_client:
        test_client.get("/auth/login", params={"as": "alice"})
        assert "me.entries.none" in test_client.get("/me").text
        first = generate_seed(test_client)
        second = generate_seed(test_client)
        post_download(test_client, first, name="luigi", clubs=("1W", "PW"))
        test_client.get("/auth/login", params={"as": "bob"})
        post_download(test_client, second, name="toad")
        bob_page = test_client.get("/me").text
        test_client.get("/auth/login", params={"as": "alice"})
        post_download(test_client, second, name="peach")
        with app_state(test_client).db.transaction() as conn:
            conn.execute(
                "UPDATE entries SET created_at = '2026-01-01T00:00:00Z' WHERE seed_id = ?",
                (first,),
            )
        alice_page = test_client.get("/me").text
    assert 'aria-current="page"' in alice_page[: alice_page.index("</nav>")]
    assert "me.entries.none" not in alice_page
    assert alice_page.index(f'href="/h/{second}"') < alice_page.index(
        f'href="/h/{first}"'
    )
    assert "<td>LUIGI</td>" in alice_page
    assert "<td>1W PW PT</td>" in alice_page
    assert "<td>PEACH</td>" in alice_page
    assert "<td>TOAD</td>" not in alice_page
    assert f'href="/h/{first}"' not in bob_page


def test_my_page_lists_my_rounds(fake_builder):
    with dev_client(fake_builder, strings=UNWRITTEN) as test_client:
        seed_id = entered_seed(test_client, "bob", "alice")
        assert "me.rounds.none" in test_client.get("/me").text
        test_client.get(scan_path(test_client, seed_id, "alice", slot=1, strokes=5))
        test_client.get(scan_path(test_client, seed_id, "bob", strokes=3))
        player_two_only = test_client.get("/me").text
        test_client.get(scan_path(test_client, seed_id, "alice", slot=0, strokes=4))
        page = test_client.get("/me").text
    assert "me.rounds.none" not in page
    rounds = page[page.index('class="rounds') :]
    # only the player 2 round's magic words carry the asterisk
    assert rounds.count("</a>*</td>") == 1
    assert rounds.count('class="magic-words"') == 3
    assert len(set(re.findall(r'href="(/r/\w{10})"', rounds))) == 2
    assert "</a>*</td>" in player_two_only[player_two_only.index('class="rounds') :]
    assert ">90</a>" in rounds
    assert ">54</a>" not in rounds


def test_discord_failing_is_logged(fake_builder, caplog):
    with TestClient(
        create_app(
            DISCORD_CONFIG,
            strings=UNWRITTEN,
            builder=fake_builder,
            discord=FakeDiscord(None),
        )
    ) as test_client:
        state = start_discord_sign_in(test_client)
        with caplog.at_level(logging.WARNING, logger="server.routes.account"):
            test_client.get("/auth/callback", params={"code": "abc", "state": state})
    assert "Discord sign-in failed" in caplog.text
