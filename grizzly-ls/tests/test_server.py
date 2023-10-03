import logging

from typing import Optional, Dict, Any, List, cast
from pathlib import Path
from concurrent import futures
from tempfile import gettempdir
from shutil import rmtree
from unittest.mock import ANY

import pytest
import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pygls.workspace import Workspace, Document
from pygls.server import LanguageServer
from lsprotocol.types import (
    TEXT_DOCUMENT_COMPLETION,
    INITIALIZE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_DEFINITION,
    Hover,
    ClientCapabilities,
    CompletionContext,
    CompletionParams,
    CompletionItemKind,
    CompletionList,
    CompletionItem,
    DidOpenTextDocumentParams,
    DefinitionParams,
    InitializeParams,
    LocationLink,
    Position,
    HoverParams,
    TextDocumentItem,
    TextDocumentIdentifier,
    MarkupKind,
    MarkupContent,
    MessageType,
)
from behave.matchers import ParseMatcher

from .fixtures import LspFixture
from .helpers import normalize_completion_item
from grizzly_ls import __version__
from grizzly_ls.server import GrizzlyLanguageServer, Progress


def test_progress(lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
    server = lsp_fixture.server

    progress = Progress(server.progress, title='test')

    assert progress.progress is server.progress
    assert progress.title == 'test'
    assert isinstance(progress.token, str)

    report_spy = mocker.spy(progress, 'report')
    progress_create_mock = mocker.patch.object(
        progress.progress, 'create', return_value=None
    )
    progress_begin_mock = mocker.patch.object(
        progress.progress, 'begin', return_value=None
    )
    progress_end_mock = mocker.patch.object(
        progress.progress,
        'end',
        return_value=None,
    )
    progress_report_mock = mocker.patch.object(
        progress.progress, 'report', return_value=None
    )

    with progress as p:
        p.report('first', 50)
        p.report('second', 99)

    progress_create_mock.assert_called_once_with(progress.token, progress.callback)
    progress_begin_mock.assert_called_once_with(progress.token, ANY)
    progress_end_mock.assert_called_once_with(progress.token, ANY)

    assert progress_report_mock.call_count == 3
    assert report_spy.call_count == 3


class TestGrizzlyLanguageServer:
    def test___init__(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server.name == 'grizzly-ls'
        assert server.version == __version__
        assert server.steps == {}
        assert sorted(server.keywords) == sorted(['Scenario', 'And', 'But'])
        assert sorted(server.keywords_any) == sorted(
            [
                '*',
                'But',
                'And',
            ]
        )
        assert sorted(server.keywords_once) == sorted(['Feature', 'Background'])

        assert isinstance(server.logger, logging.Logger)
        assert server.logger.name == 'grizzly_ls.server'

    def test_show_message(
        self,
        lsp_fixture: LspFixture,
        caplog: LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        server = lsp_fixture.server
        show_message_mock = mocker.patch(
            'pygls.server.LanguageServer.show_message', return_value=None
        )

        message = 'implicit INFO level'
        with caplog.at_level(logging.INFO):
            server.show_message(message)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Info)
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'explicit INFO level'
        with caplog.at_level(logging.INFO):
            server.show_message(message, MessageType.Info)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Info)
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'ERROR level'
        with caplog.at_level(logging.ERROR):
            server.show_message(message, MessageType.Error)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Error)
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'WARNING level'
        with caplog.at_level(logging.WARNING):
            server.show_message(message, MessageType.Warning)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Warning)
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'DEBUG level'
        with caplog.at_level(logging.DEBUG):
            server.show_message(message, MessageType.Debug)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Debug)
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'CRITICAL level'
        with caplog.at_level(logging.CRITICAL):
            server.show_message(message, MessageType.Debug)
        assert caplog.messages == []
        show_message_mock.assert_called_once_with(message, msg_type=MessageType.Debug)
        show_message_mock.reset_mock()
        caplog.clear()

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
                'get "" with name "" and save response payload in ""',
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

            actual_completed_steps = server._complete_step('And', 'repeat for "1" it')

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_insert_text = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
                'insert_text',
            )

            assert sorted(matched_insert_text) == sorted(['iteration', 'iterations'])

            actual_completed_steps = server._complete_step('And', 'repeat for "1"')

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_insert_text = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
                'insert_text',
            )

            assert sorted(matched_insert_text) == sorted([' iteration', ' iterations'])

            actual_completed_steps = server._complete_step('And', 'repeat for "1" ')

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_insert_text = normalize_completion_item(
                actual_completed_steps,
                CompletionItemKind.Function,
                'insert_text',
            )

            assert sorted(matched_insert_text) == sorted(['iteration', 'iterations'])

            actual_completed_steps = server._complete_step(
                'Then', 'parse date "{{ datetime.now() }}" '
            )
            assert len(actual_completed_steps) == 1
            actual_completed_step = actual_completed_steps[0]
            assert actual_completed_step.insert_text == 'and save in variable "$1"'

            actual_completed_steps = server._complete_step(
                'Then', 'parse date "{{ datetime.now() }}"'
            )
            assert len(actual_completed_steps) == 1
            actual_completed_step = actual_completed_steps[0]
            assert actual_completed_step.insert_text == ' and save in variable "$1"'

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

        assert caplog.messages == []
        show_message_mock.assert_not_called()

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
                initialization_options=None,  # @TODO: should we mock some settings?
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
                        ).result(timeout=89)

                        client.lsp.send_request(  # type: ignore
                            GrizzlyLanguageServer.FEATURE_INSTALL,
                            {},
                        ).result(timeout=89)
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
            position: Optional[Position] = None,
        ) -> Optional[CompletionList]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'
            self._open(client, path, content)

            lines = content.split('\n')
            line = len(lines) - 1
            character = len(lines[-1])

            if character < 0:
                character = 0

            if position is None:
                position = Position(line=line, character=character)

            params = CompletionParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=position,
                context=context,
                partial_result_token=None,
                work_done_token=None,
            )

            response = client.lsp.send_request(TEXT_DOCUMENT_COMPLETION, params).result(timeout=3)  # type: ignore

            assert response is None or isinstance(response, CompletionList)

            return cast(Optional[CompletionList], response)

        def _hover(
            self,
            client: LanguageServer,
            path: Path,
            position: Position,
            content: Optional[str] = None,
        ) -> Optional[Hover]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'

            self._open(client, path, content)

            params = HoverParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=position,
            )

            response = client.lsp.send_request(TEXT_DOCUMENT_HOVER, params).result(timeout=3)  # type: ignore

            assert response is None or isinstance(response, Hover)

            return cast(Optional[Hover], response)

        def _definition(
            self,
            client: LanguageServer,
            path: Path,
            position: Position,
            content: Optional[str] = None,
        ) -> Optional[List[LocationLink]]:
            self._initialize(client, path)

            path = path / 'features' / 'project.feature'
            self._open(client, path, content)

            params = DefinitionParams(
                text_document=TextDocumentIdentifier(
                    uri=path.as_uri(),
                ),
                position=position,
            )

            response = client.lsp.send_request(TEXT_DOCUMENT_DEFINITION, params).result(timeout=3)  # type: ignore

            assert response is None or isinstance(response, list)

            return cast(Optional[List[LocationLink]], response)

        def test_initialize(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client
            server = lsp_fixture.server

            assert server.steps == {}

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
                items: List[CompletionItem],
            ) -> List[Dict[str, Any]]:
                return [
                    {
                        key: getattr(item, key)
                        for key in item.__dir__()
                        if key in ['label', 'kind']
                    }
                    for item in items
                ]

            # partial match, keyword containing 'B'
            response = self._completion(
                client,
                lsp_fixture.datadir,
                ''''Feature:
    Scenario:
        B''',
            )

            assert response is not None
            assert not response.is_incomplete
            assert filter_keyword_properties(response.items) == [
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
            assert response is not None
            assert not response.is_incomplete
            assert filter_keyword_properties(response.items) == [
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
            assert response is not None
            assert not response.is_incomplete
            unexpected_kinds = list(
                filter(lambda k: k != 14, map(lambda k: k.kind, response.items))
            )
            assert len(unexpected_kinds) == 0
            labels = list(map(lambda k: k.label, response.items))
            assert all([True if label is not None else False for label in labels])
            assert labels == ['Feature']

        def test_completion_steps(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            # all Given/And steps
            for keyword in ['Given', 'And']:
                response = self._completion(client, lsp_fixture.datadir, keyword)
                assert response is not None
                assert not response.is_incomplete
                unexpected_kinds = list(
                    filter(
                        lambda s: s != 3,
                        map(lambda s: s.kind, response.items),
                    )
                )
                assert len(unexpected_kinds) == 0

                labels = list(
                    map(lambda s: s.label, response.items),
                )
                assert len(labels) > 0
                assert all([True if label is not None else False for label in labels])

                assert 'ask for value of variable ""' in labels
                assert 'spawn rate is "" user per second' in labels
                assert 'spawn rate is "" users per second' in labels
                assert 'a user of type "" with weight "" load testing ""' in labels

            response = self._completion(client, lsp_fixture.datadir, 'Given value')
            assert response is not None
            assert not response.is_incomplete
            unexpected_kinds = list(
                filter(
                    lambda s: s != 3,
                    map(lambda s: s.kind, response.items),
                )
            )
            assert len(unexpected_kinds) == 0

            labels = list(
                map(lambda s: s.label, response.items),
            )
            assert len(labels) > 0
            assert all([True if label is not None else False for label in labels])

            assert 'ask for value of variable ""' in labels
            assert 'value for variable "" is ""'

            response = self._completion(client, lsp_fixture.datadir, 'Given a user of')
            assert response is not None
            assert not response.is_incomplete
            unexpected_kinds = list(
                filter(
                    lambda s: s != 3,
                    map(lambda s: s.kind, response.items),
                )
            )
            assert len(unexpected_kinds) == 0

            labels = list(
                map(lambda s: s.label, response.items),
            )
            assert len(labels) > 0
            assert all([True if label is not None else False for label in labels])

            assert 'a user of type "" with weight "" load testing ""' in labels
            assert 'a user of type "" load testing ""' in labels

            response = self._completion(
                client, lsp_fixture.datadir, 'Then parse date "{{ datetime.now() }}"'
            )
            assert response is not None
            assert not response.is_incomplete

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                map(lambda s: s.insert_text, response.items),
            )

            assert labels == [
                'parse date "{{ datetime.now() }}" and save in variable ""'
            ]
            assert insert_texts == [' and save in variable "$1"']

        def test_completion_variable_names(
            self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
        ) -> None:
            client = lsp_fixture.client

            content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then parse date "{{'''
            response = self._completion(client, lsp_fixture.datadir, content)

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' price }}"', ' foo }}"', ' test }}"', ' bar }}"']
            )
            assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

            content = '''Feature: test
    Scenario: test1
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then log message "{{

    Scenario: test2
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "weight" is "200"
        And value for variable "hello" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "world"

        Then log message "{{ "

    Scenario: test3
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "weight" is "200"
        And value for variable "hello" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "world"

        Then log message "{{ }}"'''

            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=Position(line=8, character=28),
            )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' price }}"', ' foo }}"', ' test }}"', ' bar }}"']
            )
            assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=Position(line=17, character=28),
            )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' weight }}', ' hello }}', ' test }}', ' world }}']
            )
            assert sorted(labels) == sorted(['weight', 'hello', 'test', 'world'])

            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=Position(line=26, character=28),
            )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' weight', ' hello', ' test', ' world']
            )
            assert sorted(labels) == sorted(['weight', 'hello', 'test', 'world'])

            content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then parse date "{{" and save in variable ""'''
            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=Position(line=8, character=27),
            )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' price }}', ' foo }}', ' test }}', ' bar }}']
            )
            assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

            content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then send request "test/request.j2.json" with name "{{" to endpoint ""
        Then send request "{{}}" with name "" to endpoint ""'''
            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=Position(line=8, character=62),
            )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [' price }}', ' foo }}', ' test }}', ' bar }}']
            )
            assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

            with caplog.at_level(logging.DEBUG):
                response = self._completion(
                    client,
                    lsp_fixture.datadir,
                    content,
                    position=Position(line=9, character=29),
                )

            assert response is not None

            labels = list(
                map(lambda s: s.label, response.items),
            )
            insert_texts = list(
                [s.insert_text for s in response.items if s.insert_text is not None]
            )

            assert sorted(insert_texts) == sorted(
                [
                    ' price ',
                    ' foo ',
                    ' test ',
                    ' bar ',
                ]
            )
            assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

        def test_hover(self, lsp_fixture: LspFixture) -> None:
            client = lsp_fixture.client

            response = self._hover(
                client, lsp_fixture.datadir, Position(line=2, character=31)
            )

            assert response is not None
            assert response.range is not None

            assert response.range.end.character == 85
            assert response.range.end.line == 2
            assert response.range.start.character == 4
            assert response.range.start.line == 2
            assert isinstance(response.contents, MarkupContent)
            assert response.contents.kind == MarkupKind.Markdown
            assert (
                response.contents.value
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
                assert response is not None
                assert len(response) == 1
                actual_definition = response[0]
                assert actual_definition.target_uri == test_txt_file.as_uri()
                assert actual_definition.target_range.start.line == 0
                assert actual_definition.target_range.start.character == 0
                assert actual_definition.target_range.end.line == 0
                assert actual_definition.target_range.end.character == 0
                assert actual_definition.target_selection_range.start.line == 0
                assert actual_definition.target_selection_range.start.character == 0
                assert actual_definition.target_selection_range.end.line == 0
                assert actual_definition.target_selection_range.end.character == 0
                assert actual_definition.origin_selection_range is not None
                assert actual_definition.origin_selection_range.start.line == 3
                assert actual_definition.origin_selection_range.start.character == 23
                assert actual_definition.origin_selection_range.end.line == 3
                assert actual_definition.origin_selection_range.end.character == 36
            finally:
                rmtree(request_payload_dir)
