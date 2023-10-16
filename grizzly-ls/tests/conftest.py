from typing import Generator
from pathlib import Path

import pytest

from .fixtures import LspFixture


def _lsp_fixture() -> Generator[LspFixture, None, None]:
    with LspFixture() as fixture:
        yield fixture


lsp_fixture = pytest.fixture(scope='session')(_lsp_fixture)

GRIZZLY_PROJECT = (Path(__file__) / '..' / '..' / '..' / 'tests' / 'project').resolve()

assert GRIZZLY_PROJECT.is_dir()
