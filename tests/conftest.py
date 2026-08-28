"""Fixtures shared by the MySkoda PublicAPI tests."""

import pytest
from aioresponses import aioresponses


@pytest.fixture
def api():
    """Intercept every call to the MyŠkoda API."""
    with aioresponses() as mocked:
        yield mocked
