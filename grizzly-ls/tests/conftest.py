from typing import Generator

import pytest

from .fixtures import LspFixture


def _lsp_fixture() -> Generator[LspFixture, None, None]:
    with LspFixture() as fixture:
        yield fixture


lsp_fixture = pytest.fixture(scope='module')(_lsp_fixture)
