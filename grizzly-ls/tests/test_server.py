import logging

from typing import Optional, Dict, Any, cast
from pathlib import Path
from concurrent import futures
from tempfile import gettempdir
from shutil import rmtree

import pytest

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pygls.lsp.types.basic_structures import Position
from pygls.workspace import Workspace, Document
from pygls.server import LanguageServer
from pygls.lsp.methods import (
    COMPLETION,
    INITIALIZE,
    TEXT_DOCUMENT_DID_OPEN,
)
from pygls.lsp.types import (
    ClientCapabilities,
    CompletionContext,
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind,
    DidOpenTextDocumentParams,
    InitializeParams,
)
from pygls.lsp.types.basic_structures import Position, TextDocumentItem, TextDocumentIdentifier
from behave.matchers import ParseMatcher
from grizzly_ls.server import GrizzlyLanguageServer

from .fixtures import LspFixture


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

    def test__get_step_expressions(self, mocker: MockerFixture) -> None:
        mocker.patch('parse.Parser.__init__', return_value=None)
        server = GrizzlyLanguageServer()

        assert server.steps == {}

        noop = lambda: None

        step = ParseMatcher(noop, 'hello world')

        assert server._get_step_expressions(step) == ['hello world']  # type: ignore

        step = ParseMatcher(noop, 'hello "{world}"! how "{are:d}" you')

        assert server._get_step_expressions(step) == ['hello ""! how "" you']  # type: ignore

        step = ParseMatcher(noop, 'you have "{count}" {grammar:UserGramaticalNumber}')

        assert sorted(server._get_step_expressions(step)) == sorted([  # type: ignore
            'you have "" users',
            'you have "" user',
        ])

        step = ParseMatcher(noop, 'send from {from_node:MessageDirection} to {to_node:MessageDirection}')

        assert sorted(server._get_step_expressions(step)) == sorted([  # type: ignore
            'send from client to server',
            'send from server to client',
        ])


    def test__make_step_registry(self, caplog: LogCaptureFixture) -> None:
        server = GrizzlyLanguageServer()

        assert server.steps == {}

        grizzly_project = Path.cwd() / '..' / 'tests' / 'project'

        with caplog.at_level(logging.DEBUG, 'grizzly_ls.server'):
            server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))  # type: ignore

        assert len(caplog.messages) == 3

        assert not server.steps == {}

        keywords = list(server.steps.keys())

        for keyword in ['given', 'then', 'when']:
            assert keyword in keywords

    def test__make_keyword_registry(self) -> None:
        server = GrizzlyLanguageServer()

        assert server.steps == {}
        assert server.keywords == []

        # create pre-requisites
        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))  # type: ignore

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

    class TestGrizzlyLangageServerFeatures:
        def _initialize(self, client: LanguageServer, root: Path) -> None:
            retry = 3
            params = InitializeParams(
                process_id=1337,
                capabilities=ClientCapabilities(),
                root_uri=root.as_uri(),
                root_path=str(root),
            )

            logger = logging.getLogger()
            level = logger.getEffectiveLevel()
            try:
                logger.setLevel(logging.ERROR)

                while retry > 0:
                    try:
                        client.lsp.send_request(  # type: ignore
                            INITIALIZE,
                            params,
                        ).result(timeout=59)
                    except futures.TimeoutError:
                        retry -= 1
                    else:
                        break
            finally:
                logger.setLevel(level)


        def _open(self, client: LanguageServer, path: Path, text: Optional[str] = None) -> None:
            if text is None:
                text = path.read_text()

            client.lsp.notify(  # type: ignore
                TEXT_DOCUMENT_DID_OPEN,
                DidOpenTextDocumentParams(
                    text_document=TextDocumentItem(
                        uri=path.as_uri(),
                        language_id='grizzly-gherkin',
                        version=1,
                        text=text,
                    ),
                ),
            )

        def _completion(self, client: LanguageServer, path: Path, content: str, context: Optional[CompletionContext] = None) -> Dict[str, Any]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'
            self._open(client, path, content)

            params = CompletionParams(
                text_document=TextDocumentIdentifier(uri=path.as_uri()),
                position=Position(line=0, character=len(content)),
                context=context,
            )

            if context is None:
                del params.context

            response = client.lsp.send_request(COMPLETION, params).result(timeout=3)  # type: ignore

            assert isinstance(response, dict)

            return cast(Dict[str, Any], response)

        @pytest.mark.timeout(60)
        def test_initialize(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client
            server = lsp_fixture.server

            assert server.steps == {}
            assert server.keywords == []

            virtual_environment = Path(gettempdir()) / 'grizzly-ls-project'

            if virtual_environment.exists():
                rmtree(virtual_environment)

            self._initialize(client, lsp_fixture.datadir)

            assert not server.steps == {}

            keywords = list(server.steps.keys())

            for keyword in ['given', 'then', 'when']:
                assert keyword in keywords

            assert 'Feature' not in server.keywords  # already used once in feature file
            assert 'Background' not in server.keywords  # - " -
            assert 'And' in server.keywords  # just an alias for Given, but we need want it
            assert 'Scenario' in server.keywords  # can be used multiple times
            assert 'Given' in server.keywords  # - " -
            assert 'When' in server.keywords

        def test_completion_keywords(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client
            server = lsp_fixture.server

            # partial match, keyword containing 'B'
            response = self._completion(client, lsp_fixture.datadir, 'B')

            assert not response.get('isIncomplete', True)
            items = response.get('items', [])
            assert items == [
                {
                    'label': 'Background',
                    'kind': 14,
                },
                {
                    'label': 'But',
                    'kind': 14,
                },
            ]

            # partial match, keyword containing 'en'
            response = self._completion(client, lsp_fixture.datadir, 'en')
            assert not response.get('isIncomplete', True)
            items = response.get('items', [])
            assert items == [
                {
                    'label': 'Given',
                    'kind': 14,
                },
                {
                    'label': 'Scenario',
                    'kind': 14,
                },
                {
                    'label': 'Then',
                    'kind': 14,
                },
                {
                    'label': 'When',
                    'kind': 14,
                },
            ]

            # all keywords
            response = self._completion(client, lsp_fixture.datadir, '')
            assert not response.get('isIncomplete', True)
            items = response.get('items', [])
            unexpected_kinds = list(filter(lambda k: k != 14, map(lambda k: k.get('kind', None), items)))
            assert len(unexpected_kinds) == 0
            labels = list(map(lambda k: k.get('label', None), items))
            assert all([True if l is not None else False for l in labels])

            for keyword in server.keywords + server.keywords_once + list(server.keyword_alias.keys()):
                assert keyword in labels

        def test_completion_steps(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            # all Given/And steps
            for keyword in ['Given', 'And']:
                response = self._completion(client, lsp_fixture.datadir, keyword)
                assert not response.get('isIncomplete', True)
                unexpected_kinds = list(filter(lambda s: s != 3, map(lambda s: s.get('kind', None), response.get('items', []))))
                assert len(unexpected_kinds) == 0

                labels = list(map(lambda s: s.get('label', None), response.get('items', [])))
                assert len(labels) > 0
                assert all([True if l is not None else False for l in labels])

                assert 'ask for value of variable "{name}"' in labels
                assert 'spawn rate is "{value}" {grammar:UserGramaticalNumber} per second' in labels
                assert 'a user of type "{user_class_name}" with weight "{weight_value}" load testing "{host}"' in labels

            response = self._completion(client, lsp_fixture.datadir, 'Given value')
            assert not response.get('isIncomplete', True)
            unexpected_kinds = list(filter(lambda s: s != 3, map(lambda s: s.get('kind', None), response.get('items', []))))
            assert len(unexpected_kinds) == 0

            labels = list(map(lambda s: s.get('label', None), response.get('items', [])))
            print(labels)
            assert len(labels) > 0
            assert all([True if l is not None else False for l in labels])

            assert 'ask for value of variable "{name}"' in labels
            assert 'spawn rate is "{value}" {grammar:UserGramaticalNumber} per second' not in labels
            assert 'a user of type "{user_class_name}" with weight "{weight_value}" load testing "{host}"' in labels

