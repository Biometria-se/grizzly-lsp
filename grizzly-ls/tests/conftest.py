from typing import Generator

import pytest

from pytest_mock import MockerFixture

from .fixtures import LspFixture


@pytest.mark.usefixtures('mocker')
def _lsp_fixture(mocker: MockerFixture) -> Generator[LspFixture, None, None]:
    with LspFixture(mocker) as fixture:
        yield fixture


lsp_fixture = pytest.fixture(scope='function')(_lsp_fixture)
