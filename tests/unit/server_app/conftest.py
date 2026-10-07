"""Fixtures for the tests that drive the whole app through a `TestClient`."""

import pytest

from golf.randomizer.catalog import Catalog, HoleStore
from golf.randomizer.curation import CurationSnapshot
from tests.unit.server_app.helpers import UNWRITTEN, FakeBuilder, app_client


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load()


@pytest.fixture(scope="module")
def curation() -> CurationSnapshot:
    return CurationSnapshot.load()


@pytest.fixture
def fake_builder(catalog, curation, tmp_path):
    return FakeBuilder(catalog, curation, HoleStore(), tmp_path / "unused.nes")


@pytest.fixture
def client(fake_builder):
    with app_client(builder=fake_builder) as test_client:
        yield test_client


@pytest.fixture
def unwritten_client(fake_builder):
    """For tests that name the notice a page shows by its key rather than by what it says."""
    with app_client(strings=UNWRITTEN, builder=fake_builder) as test_client:
        yield test_client
