import logging
from pathlib import Path

import pytest

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pygls.lsp.types.basic_structures import Position
from pygls.workspace import Workspace, Document
from grizzly_ls.server import GrizzlyLanguageServer


class TestGrizzlyLanguageServer:
    def test___init__(self) -> None:
        server = GrizzlyLanguageServer()

        assert server.steps == {}
        assert server.keywords == []
        assert server.keyword_alias == {
            'But': 'Then',
            'And': 'Given',
        }
        assert server.keywords_once == ['Feature', 'Background']

        assert isinstance(server.logger, logging.Logger)
        assert server.logger.name == 'grizzly_ls.server'

        assert 0

    def test__make_step_registry(self, caplog: LogCaptureFixture) -> None:
        server = GrizzlyLanguageServer()

        assert server.steps == {}

        grizzly_project = Path.cwd() / '..' / 'tests' / 'project'

        with caplog.at_level(logging.DEBUG, 'grizzly_ls.server'):
            server._make_step_registry((grizzly_project / 'features' / 'steps'))  # type: ignore

        assert len(caplog.messages) == 1

        assert not server.steps == {}

        keywords = list(server.steps.keys())

        for keyword in ['given', 'then', 'when']:
            assert keyword in keywords

    def test__make_keyword_registry(self) -> None:
        server = GrizzlyLanguageServer()

        assert server.steps == {}
        assert server.keywords == []

        # create pre-requisites
        grizzly_project = Path.cwd() / '..' / 'tests' / 'project'
        server._make_step_registry((grizzly_project / 'features' / 'steps'))  # type: ignore

        server._make_keyword_registry()  # type: ignore

        assert 'Feature' not in server.keywords  # already used once in feature file
        assert 'Background' not in server.keywords  # - " -
        assert 'And' in server.keywords  # just an alias for Given, but we need want it
        assert 'Scenario' in server.keywords  # can be used multiple times
        assert 'Given' in server.keywords  # - " -
        assert 'When' in server.keywords

    def test__current_line(self, mocker: MockerFixture) -> None:
        server = GrizzlyLanguageServer()

        mocker.patch.object(server.lsp, 'workspace', Workspace('', None))
        mocker.patch('tests.test_server.Workspace.get_document', return_value=Document('file://test.feature', '''Feature:
    Scenario: test
        Then hello world!
        But foo bar
'''))

        assert server._current_line('file://test.feature', Position(line=0, character=0)).strip() == 'Feature:'  # type: ignore
        assert server._current_line('file://test.feature', Position(line=1, character=543)).strip() == 'Scenario: test'  # type: ignore
        assert server._current_line('file://test.feature', Position(line=2, character=435)).strip() == 'Then hello world!'  # type: ignore
        assert server._current_line('file://test.feature', Position(line=3, character=534)).strip() == 'But foo bar'  # type: ignore

        with pytest.raises(IndexError) as ie:
            assert server._current_line('file://test.feature', Position(line=10, character=10)).strip() == 'Then hello world!'  # type: ignore
        assert str(ie.value) == 'list index out of range'


