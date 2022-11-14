import logging

from typing import Optional, Dict, Any, List, cast
from pathlib import Path
from concurrent import futures
from tempfile import gettempdir
from shutil import rmtree

import pytest
import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pygls.workspace import Workspace, Document
from pygls.server import LanguageServer
from pygls.lsp.methods import (
    COMPLETION,
    INITIALIZE,
    TEXT_DOCUMENT_DID_OPEN,
    HOVER,
    DEFINITION,
)
from pygls.lsp.types import (
    ClientCapabilities,
    CompletionContext,
    CompletionParams,
    CompletionItemKind,
    DidOpenTextDocumentParams,
    InitializeParams,
)
from pygls.lsp.types.basic_structures import (
    Position,
    TextDocumentItem,
    TextDocumentIdentifier,
    TextDocumentPositionParams,
)
from behave.matchers import ParseMatcher

from .fixtures import LspFixture
from .helpers import normalize_completion_item
from grizzly_ls import __version__


class TestGrizzlyLanguageServer:
    def test___init__(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server.name == 'grizzly-ls'
        assert server.version == __version__
        assert server.steps == {}
        assert server.keywords == []
        assert server.keyword_any == [
            'But',
            'And',
            '*',
        ]
        assert server.keywords_once == ['Feature', 'Background']

        assert isinstance(server.logger, logging.Logger)
        assert server.logger.name == 'grizzly_ls.server'

    def test__format_arg_line(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert (
            server._format_arg_line(
                'hello_world (bool): foo bar description of argument'
            )
            == '* hello_world `bool`: foo bar description of argument'
        )
        assert (
            server._format_arg_line('hello: strange stuff (bool)')
            == '* hello: strange stuff (bool)'
        )

    def test__complete_keyword(self, lsp_fixture: LspFixture) -> None:
        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server = lsp_fixture.server
        server._compile_inventory(grizzly_project.resolve(), 'project')

        document = Document(
            uri='dummy.feature',
            source='',
        )

        assert normalize_completion_item(
            server._complete_keyword(None, document), CompletionItemKind.Keyword
        ) == [
            'Feature',
        ]

        document = Document(
            uri='dummy.feature',
            source='Feature:',
        )

        assert normalize_completion_item(
            server._complete_keyword(None, document), CompletionItemKind.Keyword
        ) == [
            'Background',
            'Scenario',
        ]

        document = Document(
            uri='dummy.feature',
            source='''Feature:
    Scenario:
''',
        )

        assert normalize_completion_item(
            server._complete_keyword(None, document), CompletionItemKind.Keyword
        ) == [
            'And',
            'Background',
            'But',
            'Given',
            'Scenario',
            'Then',
            'When',
        ]

        document = Document(
            uri='dummy.feature',
            source='''Feature:
    Background:
        Given a bunch of stuff
    Scenario:
''',
        )

        assert normalize_completion_item(
            server._complete_keyword(None, document), CompletionItemKind.Keyword
        ) == [
            'And',
            'But',
            'Given',
            'Scenario',
            'Then',
            'When',
        ]

        assert normalize_completion_item(
            server._complete_keyword('EN', document), CompletionItemKind.Keyword
        ) == [
            'Given',
            'Scenario',
            'Then',
            'When',
        ]

        assert normalize_completion_item(
            server._complete_keyword('Giv', document), CompletionItemKind.Keyword
        ) == [
            'Given',
        ]

    def test__complete_step(
        self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
    ) -> None:
        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server = lsp_fixture.server
        server._compile_inventory(grizzly_project.resolve(), 'project')

        with caplog.at_level(logging.DEBUG):
            matched_steps = normalize_completion_item(
                server._complete_step('Given', 'variable'), CompletionItemKind.Function
            )

            for expected_step in [
                'set context variable "" to ""',
                'ask for value of variable ""',
                'set global context variable "" to ""',
                'set alias "" for variable ""',
                'value for variable "" is ""',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step('Then', 'save'), CompletionItemKind.Function
            )
            for expected_step in [
                'save response metadata "" in variable ""',
                'save response payload "" in variable ""',
                'save response payload "" that matches "" in variable ""',
                'save response metadata "" that matches "" in variable ""',
                'get "" with name "" and save response in ""',
                'parse date "" and save in variable ""',
                'parse "" as "undefined" and save value of "" in variable ""',
                'parse "" as "plain" and save value of "" in variable ""',
                'parse "" as "xml" and save value of "" in variable ""',
                'parse "" as "json" and save value of "" in variable ""',
            ]:
                assert expected_step in matched_steps

            suggested_steps = server._complete_step(
                'Then', 'save response metadata "hello"'
            )
            matched_steps = normalize_completion_item(
                suggested_steps, CompletionItemKind.Function
            )

            for expected_step in [
                'save response metadata "hello" in variable ""',
                'save response metadata "hello" that matches "" in variable ""',
            ]:
                assert expected_step in matched_steps

            for suggested_step in suggested_steps:
                if (
                    suggested_step.label
                    == 'save response metadata "hello" that matches "" in variable ""'
                ):
                    assert (
                        suggested_step.insert_text
                        == ' that matches "$1" in variable "$2"'
                    )
                elif (
                    suggested_step.label
                    == 'save response metadata "hello" in variable ""'
                ):
                    assert suggested_step.insert_text == ' in variable "$1"'
                else:
                    raise AssertionError(
                        f'"{suggested_step.label}" was an unexpected suggested step'
                    )

            matched_steps = normalize_completion_item(
                server._complete_step('When', None), CompletionItemKind.Function
            )

            for expected_step in [
                'condition "" with name "" is true, execute these tasks',
                'fail ratio is greater than ""% fail scenario',
                'average response time is greater than "" milliseconds fail scenario',
                'response time percentile ""% is greater than "" milliseconds fail scenario',
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step('When', 'response '), CompletionItemKind.Function
            )

            for expected_step in [
                'response time percentile ""% is greater than "" milliseconds fail scenario',
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step('When', 'response fail request'),
                CompletionItemKind.Function,
            )

            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step('When', 'response payload "" is fail request'),
                CompletionItemKind.Function,
            )

            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step(
                    'Given', 'a user of type "RestApi" with weight "1" load'
                ),
                CompletionItemKind.Function,
            )

            assert len(matched_steps) == 1
            assert (
                matched_steps[0]
                == 'a user of type "RestApi" with weight "1" load testing ""'
            )

    def test__normalize_step_expression(
        self, lsp_fixture: LspFixture, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch('parse.Parser.__init__', return_value=None)
        server = lsp_fixture.server

        assert server.steps == {}

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'

        server._compile_inventory(grizzly_project.resolve(), 'project')

        noop = lambda: None  # noqa: E731

        step = ParseMatcher(noop, 'hello world')

        assert server._normalize_step_expression(step) == ['hello world']

        step = ParseMatcher(noop, 'hello "{world}"! how "{are:d}" you')

        assert server._normalize_step_expression(step) == ['hello ""! how "" you']

        step = ParseMatcher(noop, 'you have "{count}" {grammar:UserGramaticalNumber}')

        assert sorted(server._normalize_step_expression(step)) == sorted(
            [
                'you have "" users',
                'you have "" user',
            ]
        )

        step = ParseMatcher(
            noop, 'send from {from_node:MessageDirection} to {to_node:MessageDirection}'
        )

        assert sorted(server._normalize_step_expression(step)) == sorted(
            [
                'send from client to server',
                'send from server to client',
            ]
        )

        assert sorted(
            server._normalize_step_expression(
                'send to {to_node:MessageDirection} from {from_node:MessageDirection} for "{iterations}" {grammar:IterationGramaticalNumber}',
            )
        ) == sorted(
            [
                'send to server from client for "" iteration',
                'send to server from client for "" iterations',
                'send to client from server for "" iteration',
                'send to client from server for "" iterations',
            ]
        )

        assert sorted(
            server._normalize_step_expression(
                'send {direction:Direction} {node:MessageDirection}',
            )
        ) == sorted(
            [
                'send from server',
                'send from client',
                'send to server',
                'send to client',
            ]
        )

        step = ParseMatcher(
            noop,
            'Then save {target:ResponseTarget} as "{content_type:ContentType}" in "{variable}" for "{count}" {grammar:UserGramaticalNumber}',
        )
        actual = sorted(server._normalize_step_expression(step))
        assert actual == sorted(
            [
                'Then save payload as "undefined" in "" for "" user',
                'Then save payload as "undefined" in "" for "" users',
                'Then save metadata as "undefined" in "" for "" user',
                'Then save metadata as "undefined" in "" for "" users',
                'Then save payload as "json" in "" for "" user',
                'Then save payload as "json" in "" for "" users',
                'Then save metadata as "json" in "" for "" user',
                'Then save metadata as "json" in "" for "" users',
                'Then save payload as "xml" in "" for "" user',
                'Then save payload as "xml" in "" for "" users',
                'Then save metadata as "xml" in "" for "" user',
                'Then save metadata as "xml" in "" for "" users',
                'Then save payload as "plain" in "" for "" user',
                'Then save payload as "plain" in "" for "" users',
                'Then save metadata as "plain" in "" for "" user',
                'Then save metadata as "plain" in "" for "" users',
                'Then save metadata as "multipart_form_data" in "" for "" user',
                'Then save metadata as "multipart_form_data" in "" for "" users',
                'Then save payload as "multipart_form_data" in "" for "" user',
                'Then save payload as "multipart_form_data" in "" for "" users',
            ]
        )

        assert sorted(
            server._normalize_step_expression(
                'python {condition:Condition} cool',
            )
        ) == sorted(
            [
                'python is cool',
                'python is not cool',
            ]
        )

        assert sorted(
            server._normalize_step_expression(
                '{method:Method} {direction:Direction} endpoint "{endpoint:s}"'
            )
        ) == sorted(
            [
                'send to endpoint ""',
                'send from endpoint ""',
                'post to endpoint ""',
                'post from endpoint ""',
                'put to endpoint ""',
                'put from endpoint ""',
                'receive to endpoint ""',
                'receive from endpoint ""',
                'get to endpoint ""',
                'get from endpoint ""',
            ]
        )

        caplog.clear()

        show_message_mock = mocker.patch.object(server, 'show_message', autospec=True)

        with caplog.at_level(logging.ERROR):
            assert sorted(
                server._normalize_step_expression(
                    'unhandled type {test:Unknown} for {target:ResponseTarget}',
                )
            ) == sorted(
                [
                    'unhandled type {test:Unknown} for metadata',
                    'unhandled type {test:Unknown} for payload',
                ]
            )
        assert len(caplog.messages) == 1
        assert (
            caplog.messages[-1]
            == "unhandled type: variable='{test:Unknown}', variable_type='Unknown'"
        )

        assert show_message_mock.call_count == 1
        args, kwargs = show_message_mock.call_args_list[-1]
        assert len(args) == 1
        assert (
            args[0]
            == "unhandled type: variable='{test:Unknown}', variable_type='Unknown'"
        )
        assert len(kwargs) == 1
        assert kwargs.get('msg_type', None) == 1

    def test__compile_inventory(
        self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
    ) -> None:
        server = lsp_fixture.server

        assert server.steps == {}

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'

        with caplog.at_level(logging.DEBUG, 'grizzly_ls.server'):
            server._compile_inventory(grizzly_project.resolve(), 'project')

        assert len(caplog.messages) == 2

        assert not server.steps == {}
        assert len(server.normalizer.custom_types.keys()) >= 8

        keywords = list(server.steps.keys())

        for keyword in ['given', 'then', 'when']:
            assert keyword in keywords

        assert len(server.help.keys()) >= 0

    def test__compile_keyword_inventory(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server.steps == {}
        assert server.keywords == []

        # create pre-requisites
        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server._compile_inventory(grizzly_project.resolve(), 'project')
        server._compile_keyword_inventory()

        assert 'Feature' not in server.keywords  # already used once in feature file
        assert 'Background' not in server.keywords  # - " -
        assert 'And' in server.keywords  # just an alias for Given, but we need want it
        assert 'Scenario' in server.keywords  # can be used multiple times
        assert 'Given' in server.keywords  # - " -
        assert 'When' in server.keywords

    def test__current_line(
        self, lsp_fixture: LspFixture, mocker: MockerFixture
    ) -> None:
        server = lsp_fixture.server

        mocker.patch.object(server.lsp, 'workspace', Workspace('', None))
        mocker.patch(
            'tests.test_server.Workspace.get_document',
            return_value=Document(
                'file://test.feature',
                '''Feature:
    Scenario: test
        Then hello world!
        But foo bar
''',
            ),
        )

        assert (
            server._current_line(
                'file://test.feature', Position(line=0, character=0)
            ).strip()
            == 'Feature:'
        )
        assert (
            server._current_line(
                'file://test.feature', Position(line=1, character=543)
            ).strip()
            == 'Scenario: test'
        )
        assert (
            server._current_line(
                'file://test.feature', Position(line=2, character=435)
            ).strip()
            == 'Then hello world!'
        )
        assert (
            server._current_line(
                'file://test.feature', Position(line=3, character=534)
            ).strip()
            == 'But foo bar'
        )

        with pytest.raises(IndexError) as ie:
            assert (
                server._current_line(
                    'file://test.feature', Position(line=10, character=10)
                ).strip()
                == 'Then hello world!'
            )
        assert str(ie.value) == 'list index out of range'

    def test__find_help(self, lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
        server = lsp_fixture.server

        server.help = {
            'hello world': 'this is the help for hello world',
            'hello ""': 'this is the help for hello world parameterized',
            'foo bar': 'this is the help for foo bar',
            '"" bar': 'this is the help for foo bar parameterized',
        }

        assert (
            server._find_help('Then hello world') == 'this is the help for hello world'
        )
        assert server._find_help('asdfasdf') is None
        assert server._find_help('And hello') == 'this is the help for hello world'
        assert (
            server._find_help('And hello "world"')
            == 'this is the help for hello world parameterized'
        )
        assert server._find_help('But foo') == 'this is the help for foo bar'
        assert (
            server._find_help('But "foo" bar')
            == 'this is the help for foo bar parameterized'
        )

    class TestGrizzlyLangageServerFeatures:
        def _initialize(self, client: LanguageServer, root: Path) -> None:
            retry = 3
            params = InitializeParams(
                process_id=1337,
                root_uri=root.as_uri(),
                capabilities=ClientCapabilities(
                    workspace=None,
                    text_document=None,
                    window=None,
                    general=None,
                    experimental=None,
                ),
                client_info=None,
                locale=None,
                root_path=str(root),
                initialization_options=None,
                trace=None,
                workspace_folders=None,
                work_done_token=None,
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

        def _open(
            self, client: LanguageServer, path: Path, text: Optional[str] = None
        ) -> None:
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

        def _completion(
            self,
            client: LanguageServer,
            path: Path,
            content: str,
            context: Optional[CompletionContext] = None,
        ) -> Dict[str, Any]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'
            self._open(client, path, content)

            lines = content.split('\n')
            line = len(lines) - 1
            character = len(lines[-1]) - 1

            params = CompletionParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=Position(line=line, character=character),
                context=context,
                partial_result_token=None,
                work_done_token=None,
            )

            if context is None:
                del params.context

            response = client.lsp.send_request(COMPLETION, params).result(timeout=3)  # type: ignore

            assert isinstance(response, dict)

            return cast(Dict[str, Any], response)

        def _hover(
            self,
            client: LanguageServer,
            path: Path,
            position: Position,
            content: Optional[str] = None,
        ) -> Dict[str, Any]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'

            self._open(client, path, content)

            params = TextDocumentPositionParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=position,
            )

            response = client.lsp.send_request(HOVER, params).result(timeout=3)  # type: ignore

            return cast(Dict[str, Any], response)

        def _definition(
            self,
            client: LanguageServer,
            path: Path,
            position: Position,
            content: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'
            self._open(client, path, content)

            params = TextDocumentPositionParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=position,
            )

            response = client.lsp.send_request(DEFINITION, params).result(timeout=3)  # type: ignore

            return cast(List[Dict[str, Any]], response)

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
            assert (
                'And' in server.keywords
            )  # just an alias for Given, but we need want it
            assert 'Scenario' in server.keywords  # can be used multiple times
            assert 'Given' in server.keywords  # - " -
            assert 'When' in server.keywords

        def test_completion_keywords(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            def filter_keyword_properties(
                keywords: List[Dict[str, Any]]
            ) -> List[Dict[str, Any]]:
                return [
                    {
                        key: value
                        for key, value in keyword.items()
                        if key in ['label', 'kind']
                    }
                    for keyword in keywords
                ]

            # partial match, keyword containing 'B'
            response = self._completion(
                client,
                lsp_fixture.datadir,
                ''''Feature:
    Scenario:
        B''',
            )

            assert not response.get('isIncomplete', True)
            items = response.get('items', [])
            assert filter_keyword_properties(items) == [
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
            response = self._completion(
                client,
                lsp_fixture.datadir,
                '''Feature:
    Scenario:
        en''',
            )
            assert not response.get('isIncomplete', True)
            items = response.get('items', [])
            assert filter_keyword_properties(items) == [
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
            unexpected_kinds = list(
                filter(lambda k: k != 14, map(lambda k: k.get('kind', None), items))
            )
            assert len(unexpected_kinds) == 0
            labels = list(map(lambda k: k.get('label', None), items))
            assert all([True if label is not None else False for label in labels])
            assert labels == ['Feature']

        def test_completion_steps(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            # all Given/And steps
            for keyword in ['Given', 'And']:
                response = self._completion(client, lsp_fixture.datadir, keyword)
                assert not response.get('isIncomplete', True)
                unexpected_kinds = list(
                    filter(
                        lambda s: s != 3,
                        map(lambda s: s.get('kind', None), response.get('items', [])),
                    )
                )
                assert len(unexpected_kinds) == 0

                labels = list(
                    map(lambda s: s.get('label', None), response.get('items', []))
                )
                assert len(labels) > 0
                assert all([True if label is not None else False for label in labels])

                assert 'ask for value of variable ""' in labels
                assert 'spawn rate is "" user per second' in labels
                assert 'spawn rate is "" users per second' in labels
                assert 'a user of type "" with weight "" load testing ""' in labels

            response = self._completion(client, lsp_fixture.datadir, 'Given value')
            assert not response.get('isIncomplete', True)
            unexpected_kinds = list(
                filter(
                    lambda s: s != 3,
                    map(lambda s: s.get('kind', None), response.get('items', [])),
                )
            )
            assert len(unexpected_kinds) == 0

            labels = list(
                map(lambda s: s.get('label', None), response.get('items', []))
            )
            assert len(labels) > 0
            assert all([True if label is not None else False for label in labels])

            assert 'ask for value of variable ""' in labels
            assert 'value for variable "" is ""'

            response = self._completion(client, lsp_fixture.datadir, 'Given a user of')
            assert not response.get('isIncomplete', True)
            unexpected_kinds = list(
                filter(
                    lambda s: s != 3,
                    map(lambda s: s.get('kind', None), response.get('items', [])),
                )
            )
            assert len(unexpected_kinds) == 0

            labels = list(
                map(lambda s: s.get('label', None), response.get('items', []))
            )
            assert len(labels) > 0
            assert all([True if label is not None else False for label in labels])

            assert 'a user of type "" with weight "" load testing ""' in labels
            assert 'a user of type "" load testing ""' in labels

        def test_hover(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            response = self._hover(
                client, lsp_fixture.datadir, Position(line=2, character=31)
            )

            assert response.get('range', {}).get('end', {}) == {
                'character': 85,
                'line': 2,
            }
            assert response.get('range', {}).get('start', {}) == {
                'character': 4,
                'line': 2,
            }
            assert response.get('contents', {}).get('kind', None) == 'markdown'
            assert (
                response.get('contents', {}).get('value', None)
                == '''Sets which type of users the scenario should use and which `host` is the target,
together with `weight` of the user (how many instances of this user should spawn relative to others).

Example:

``` gherkin
Given a user of type "RestApi" with weight "2" load testing "..."
Given a user of type "MessageQueue" with weight "1" load testing "..."
Given a user of type "ServiceBus" with weight "1" load testing "..."
Given a user of type "BlobStorage" with weight "4" load testing "..."
```

Args:

* user_class_name `str`: name of an implementation of users, with or without `User`-suffix
* weight_value `str`: weight value for the user, default is `1` (see [writing a locustfile](http://docs.locust.io/en/stable/writing-a-locustfile.html#weight-attribute))
* host `str`: an URL for the target host, format depends on which users is specified
'''
            )

            response = self._hover(
                client, lsp_fixture.datadir, Position(line=0, character=1)
            )

            assert response is None

            response = self._hover(
                client,
                lsp_fixture.datadir,
                Position(line=6, character=12),
                content='''Feature:
  Scenario: test
    Given a user of type "RestApi" load testing "http://localhost"
    Then do something
    """
    {
        "hello": "world"
    }
    """''',
            )

            assert response is None

        def test_definition(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            response = self._definition(
                client, lsp_fixture.datadir, Position(line=2, character=30)
            )

            assert response is None

            request_payload_dir = lsp_fixture.datadir / 'features' / 'requests' / 'test'
            request_payload_dir.mkdir(exist_ok=True, parents=True)
            try:
                test_txt_file = request_payload_dir / 'test.txt'
                test_txt_file.write_text('hello world!')
                response = self._definition(
                    client,
                    lsp_fixture.datadir,
                    Position(line=3, character=20),
                    content='''Feature:
  Scenario: test
    Given a user of type "RestApi" load testing "http://localhost"
    Then post request "test/test.txt" with name "test request" to endpoint "/api/test"
''',
                )
                assert len(response) == 1
                actual_definition = response[0]
                assert actual_definition['targetUri'] == test_txt_file.as_uri()
                assert actual_definition.get('targetRange', {}).get('start', None) == {
                    'line': 0,
                    'character': 0,
                }
                assert actual_definition.get('targetRange', {}).get('end', None) == {
                    'line': 0,
                    'character': 0,
                }
                assert actual_definition.get('targetSelectionRange', {}).get(
                    'start', None
                ) == {'line': 0, 'character': 0}
                assert actual_definition.get('targetSelectionRange', {}).get(
                    'end', None
                ) == {'line': 0, 'character': 0}
                assert actual_definition.get('originSelectionRange', {}).get(
                    'start', None
                ) == {'line': 3, 'character': 23}
                assert actual_definition.get('originSelectionRange', {}).get(
                    'end', None
                ) == {'line': 3, 'character': 36}
            finally:
                rmtree(request_payload_dir)
