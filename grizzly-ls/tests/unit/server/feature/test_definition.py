from lsprotocol import types as lsp

from grizzly_ls.server.features.definition import get_step_definition
from tests.fixtures import LspFixture


def test_get_step_definition(lsp_fixture: LspFixture) -> None:
    ls = lsp_fixture.server

    position = lsp.Position(line=0, character=0)

    assert get_step_definition(ls, position, '') is None
    assert get_step_definition(ls, position, 'Then ') is None
