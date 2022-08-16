import logging

from typing import Optional, Dict, Any, List, cast
from pathlib import Path
from concurrent import futures
from tempfile import gettempdir
from shutil import rmtree
from enum import Enum

import pytest
import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

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
    CompletionItem,
    CompletionParams,
#    CompletionList,
#    CompletionItem,
#    CompletionItemKind,
    DidOpenTextDocumentParams,
    InitializeParams,
    MessageType,
)
from pygls.lsp.types.basic_structures import Position, TextDocumentItem, TextDocumentIdentifier
from behave.matchers import ParseMatcher

from .fixtures import LspFixture

import parse
from grizzly_extras.text import permutation, PermutationEnum
from grizzly.types import MessageDirection


@parse.with_pattern(r'(hello|world|foo|bar)')
@permutation(vector=(False, True, ))
def parse_with_pattern_and_vector(text: str) -> str:
    return text


@parse.with_pattern(r'(alice|bob)')
def parse_with_pattern(text: str) -> str:
    return text


@parse.with_pattern('')
def parse_with_pattern_error(text: str) -> str:
    return text


def parse_enum_indirect(text: str) -> MessageDirection:
    return MessageDirection.from_string(text)

class DummyEnum(PermutationEnum):
    HELLO = 0
    WORLD = 1
    FOO = 2
    BAR = 3

    @classmethod
    def from_string(cls, value: str) -> 'DummyEnum':
        for enum_value in cls:
            if enum_value.name.lower() == value.lower():
                return enum_value

        raise ValueError(f'{value} is not a valid value')


class DummyEnumNoFromString(PermutationEnum):
    ERROR = 0

    @classmethod
    def magic(cls, value: str) -> str:
        return value


class DummyEnumNoFromStringType(Enum):
    ERROR = 1

    @classmethod
    def from_string(cls, value: str):
        return value


class TestGrizzlyLanguageServer:
    def test___init__(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server.steps == {}
        assert server.keywords == []
        assert server.keyword_alias == {
            'But': 'Then',
            'And': 'Given',
        }
        assert server.keywords_once == ['Feature', 'Background']

        assert isinstance(server.logger, logging.Logger)
        assert server.logger.name == 'grizzly_ls.server'

    def test__get_step_parts(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server._get_step_parts('') == (None, None, )
        assert server._get_step_parts('Giv') == ('Giv', None, )
        assert server._get_step_parts('Given hello world') == ('Given', 'hello world', )
        assert server._get_step_parts('And are you "ok"?') == ('Given', 'are you ""?', )
        assert server._get_step_parts('Then   make sure   that "value"  is "None"') == (
            'Then', 'make sure that "" is ""',
        )

    def test__complete_keyword(self, lsp_fixture: LspFixture) -> None:
        def map_keyword_completion_list(completion_list: List[CompletionItem]) -> List[Dict[str, Any]]:
            return [{'label': completion.label, 'kind': completion.kind.numerator} for completion in completion_list if completion.kind is not None]

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server = lsp_fixture.server
        server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))
        server._make_keyword_registry()

        document = Document(
            uri='dummy.feature',
            source='',
        )

        assert map_keyword_completion_list(server._complete_keyword(None, document)) == [
            {'label': 'Feature', 'kind': 14},
        ]

        document = Document(
            uri='dummy.feature',
            source='Feature:',
        )

        assert map_keyword_completion_list(server._complete_keyword(None, document)) == [
            {'label': 'Background', 'kind': 14},
            {'label': 'Scenario', 'kind': 14},
        ]

        document = Document(
            uri='dummy.feature',
            source='''Feature:
    Scenario:
''',
        )

        assert map_keyword_completion_list(server._complete_keyword(None, document)) == [
            {'label': 'And', 'kind': 14},
            {'label': 'Background', 'kind': 14},
            {'label': 'But', 'kind': 14},
            {'label': 'Given', 'kind': 14},
            {'label': 'Scenario', 'kind': 14},
            {'label': 'Then', 'kind': 14},
            {'label': 'When', 'kind': 14},
        ]

        document = Document(
            uri='dummy.feature',
            source='''Feature:
    Background:
        Given a bunch of stuff
    Scenario:
''',
        )

        assert map_keyword_completion_list(server._complete_keyword(None, document)) == [
            {'label': 'And', 'kind': 14},
            {'label': 'But', 'kind': 14},
            {'label': 'Given', 'kind': 14},
            {'label': 'Scenario', 'kind': 14},
            {'label': 'Then', 'kind': 14},
            {'label': 'When', 'kind': 14},
        ]

        assert map_keyword_completion_list(server._complete_keyword('EN', document)) == [
            {'label': 'Given', 'kind': 14},
            {'label': 'Scenario', 'kind': 14},
            {'label': 'Then', 'kind': 14},
            {'label': 'When', 'kind': 14},
        ]

        assert map_keyword_completion_list(server._complete_keyword('Giv', document)) == [
            {'label': 'Given', 'kind': 14},
        ]

    def test__complete_step(self, lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
        def map_step_completion_list(completion_list: List[CompletionItem]) -> List[Dict[str, Any]]:
            return [{'label': completion.label, 'kind': completion.kind.numerator} for completion in completion_list if completion.kind is not None]

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server = lsp_fixture.server
        server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))
        server._make_keyword_registry() 

        with caplog.at_level(logging.DEBUG):
            matched_steps = map_step_completion_list(server._complete_step('Given', 'variable'))
            for expected_step in [
                'set context variable "" to ""',
                'ask for value of variable ""',
                'set global context variable "" to ""',
                'set alias "" for variable ""',
                'value for variable "" is ""',
            ]:
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('Then', 'save'))
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
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('Then', 'save response metadata "hello"'))
            for expected_step in [
                'save response metadata "" in variable ""',
                'save response metadata "" that matches "" in variable ""',
            ]:
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('When', None))
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
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('When', 'response '))
            for expected_step in [
                'average response time is greater than "" milliseconds fail scenario',
                'response time percentile ""% is greater than "" milliseconds fail scenario',
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('When', 'response fail request'))
            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert {'kind': 3, 'label': expected_step} in matched_steps

            matched_steps = map_step_completion_list(server._complete_step('When', 'response payload "" is fail request'))
            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
            ]:
                assert {'kind': 3, 'label': expected_step} in matched_steps

    def test__normalize_step_expression(self, lsp_fixture: LspFixture, mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
        mocker.patch('parse.Parser.__init__', return_value=None)
        server = lsp_fixture.server

        assert server.steps == {}

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'

        server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))

        noop = lambda: None

        step = ParseMatcher(noop, 'hello world')

        assert server._normalize_step_expression(step) == ['hello world'] 

        step = ParseMatcher(noop, 'hello "{world}"! how "{are:d}" you')

        assert server._normalize_step_expression(step) == ['hello ""! how "" you']

        step = ParseMatcher(noop, 'you have "{count}" {grammar:UserGramaticalNumber}')

        assert sorted(server._normalize_step_expression(step)) == sorted([
            'you have "" users',
            'you have "" user',
        ])

        step = ParseMatcher(noop, 'send from {from_node:MessageDirection} to {to_node:MessageDirection}')

        assert sorted(server._normalize_step_expression(step)) == sorted([
            'send from client to server',
            'send from server to client',
        ])

        assert sorted(server._normalize_step_expression(
            'send to {to_node:MessageDirection} from {from_node:MessageDirection} for "{iterations}" {grammar:IterationGramaticalNumber}',
        )) == sorted([
            'send to server from client for "" iteration',
            'send to server from client for "" iterations',
            'send to client from server for "" iteration',
            'send to client from server for "" iterations',
        ])

        assert sorted(server._normalize_step_expression(
            'send {direction:Direction} {node:MessageDirection}',
        )) == sorted([
            'send from server',
            'send from client',
            'send to server',
            'send to client',
        ])

        step = ParseMatcher(
            noop,
            'Then save {target:ResponseTarget} as "{content_type:ContentType}" in "{variable}" for "{count}" {grammar:UserGramaticalNumber}',
        )
        actual = sorted(server._normalize_step_expression(step))
        assert actual == sorted([
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
        ])

        assert sorted(server._normalize_step_expression(
            'python {condition:Condition} cool',
        )) == sorted([
            'python is cool',
            'python is not cool',
        ])

        assert sorted(server._normalize_step_expression(
            '{method:Method} {direction:Direction} endpoint "{endpoint:s}"'
        )) == sorted([
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
        ])

        caplog.clear()

        show_message_mock = mocker.patch.object(server, 'show_message', autospec=True)

        with caplog.at_level(logging.ERROR):
            assert sorted(server._normalize_step_expression(
                'unhandled type {test:Unknown} for {target:ResponseTarget}',
            )) == sorted([
                'unhandled type {test:Unknown} for metadata', 
                'unhandled type {test:Unknown} for payload', 
            ])
        assert len(caplog.messages) == 1
        assert caplog.messages[-1] == "unhandled type: variable='{test:Unknown}', variable_type='Unknown'"

        assert show_message_mock.call_count == 1
        args, kwargs = show_message_mock.call_args_list[-1]
        assert len(args) == 1
        assert args[0] == "unhandled type: variable='{test:Unknown}', variable_type='Unknown'"
        assert len(kwargs) == 1
        assert kwargs.get('msg_type', None) == 1

    def test__resolve_custom_types(self, lsp_fixture: LspFixture, mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
        server = lsp_fixture.server

        mocker.patch('grizzly_ls.server.ParseMatcher.custom_types', {})
        show_message_spy = mocker.spy(server, 'show_message')

        server._resolve_custom_types()
        assert server.normalizer.custom_types == {}

        mocker.patch(
            'grizzly_ls.server.ParseMatcher.custom_types',
            {
                'WithPatternAndVector': parse_with_pattern_and_vector,
                'WithPattern': parse_with_pattern,
                'EnumIndirect': parse_enum_indirect,
                'EnumDirect': DummyEnum.from_string,
            },
        )
        server._resolve_custom_types()

        assert list(sorted(server.normalizer.custom_types.keys())) == sorted([
            'WithPatternAndVector',
            'WithPattern',
            'EnumIndirect',
            'EnumDirect',
        ])

        with_pattern_and_vector = server.normalizer.custom_types.get('WithPatternAndVector', None)

        assert with_pattern_and_vector is not None
        assert not with_pattern_and_vector.permutations.x and with_pattern_and_vector.permutations.y
        assert sorted(with_pattern_and_vector.replacements) == sorted(['bar', 'hello', 'foo', 'world'])

        with_pattern = server.normalizer.custom_types.get('WithPattern', None)

        assert with_pattern is not None
        assert not with_pattern.permutations.x and not with_pattern.permutations.y
        assert sorted(with_pattern.replacements) == sorted(['alice', 'bob'])

        enum_indirect = server.normalizer.custom_types.get('EnumIndirect', None)
        assert enum_indirect is not None
        assert enum_indirect.permutations.x and enum_indirect.permutations.y
        assert sorted(enum_indirect.replacements) == sorted(['client_server', 'server_client'])

        enum_direct = server.normalizer.custom_types.get('EnumDirect', None)
        assert enum_direct is not None
        assert not enum_direct.permutations.x and not enum_direct.permutations.y
        assert sorted(enum_direct.replacements) == sorted(['hello', 'world', 'foo', 'bar'])

        mocker.patch(
            'grizzly_ls.server.ParseMatcher.custom_types',
            {
                'WithPattern': parse_with_pattern_error,
            },
        )

        caplog.clear()
        with caplog.at_level(logging.ERROR):
            server._resolve_custom_types()

        assert len(caplog.messages) == 1
        expected_message = 'could not extract pattern from "@parse.with_pattern(\'\')" for custom type WithPattern'
        assert caplog.messages[-1] == expected_message
        assert show_message_spy.call_count == 1
        args, kwargs = show_message_spy.call_args_list[-1]
        assert args[0] == expected_message
        assert kwargs.get('msg_type', None) == MessageType.Error

        mocker.patch(
            'grizzly_ls.server.ParseMatcher.custom_types',
            {
                'EnumError': DummyEnumNoFromString.magic,
            },
        )

        with caplog.at_level(logging.ERROR):
            server._resolve_custom_types()

        assert len(caplog.messages) == 2
        expected_message = 'cannot infere what <bound method DummyEnumNoFromString.magic of <enum \'DummyEnumNoFromString\'>> will return for EnumError'
        assert caplog.messages[-1] == expected_message
        assert show_message_spy.call_count == 2
        args, kwargs = show_message_spy.call_args_list[-1]
        assert args[0] == expected_message
        assert kwargs.get('msg_type', None) == MessageType.Error

        mocker.patch(
            'grizzly_ls.server.ParseMatcher.custom_types',
            {
                'EnumError': DummyEnumNoFromStringType.from_string,
            },
        )

        with caplog.at_level(logging.ERROR):
            server._resolve_custom_types()

        assert len(caplog.messages) == 3
        expected_message = 'could not find the type that from_string method for custom type EnumError returns'
        assert caplog.messages[-1] == expected_message
        assert show_message_spy.call_count == 3
        args, kwargs = show_message_spy.call_args_list[-1]
        assert args[0] == expected_message
        assert kwargs.get('msg_type', None) == MessageType.Error

    def test__make_step_registry(self, lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
        server = lsp_fixture.server

        assert server.steps == {}

        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'

        with caplog.at_level(logging.DEBUG, 'grizzly_ls.server'):
            server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))

        assert len(caplog.messages) == 2

        assert not server.steps == {}
        assert len(server.normalizer.custom_types.keys()) >= 8

        keywords = list(server.steps.keys())

        for keyword in ['given', 'then', 'when']:
            assert keyword in keywords

    def test__make_keyword_registry(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        assert server.steps == {}
        assert server.keywords == []

        # create pre-requisites
        grizzly_project = Path(__file__) / '..' / '..' / '..' / 'tests' / 'project'
        server._make_step_registry((grizzly_project.resolve() / 'features' / 'steps'))
        server._make_keyword_registry()

        assert 'Feature' not in server.keywords  # already used once in feature file
        assert 'Background' not in server.keywords  # - " -
        assert 'And' in server.keywords  # just an alias for Given, but we need want it
        assert 'Scenario' in server.keywords  # can be used multiple times
        assert 'Given' in server.keywords  # - " -
        assert 'When' in server.keywords

    def test__current_line(self, lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
        server = lsp_fixture.server

        mocker.patch.object(server.lsp, 'workspace', Workspace('', None))
        mocker.patch('tests.test_server.Workspace.get_document', return_value=Document('file://test.feature', '''Feature:
    Scenario: test
        Then hello world!
        But foo bar
'''))

        assert server._current_line('file://test.feature', Position(line=0, character=0)).strip() == 'Feature:'
        assert server._current_line('file://test.feature', Position(line=1, character=543)).strip() == 'Scenario: test'
        assert server._current_line('file://test.feature', Position(line=2, character=435)).strip() == 'Then hello world!'
        assert server._current_line('file://test.feature', Position(line=3, character=534)).strip() == 'But foo bar'

        with pytest.raises(IndexError) as ie:
            assert server._current_line('file://test.feature', Position(line=10, character=10)).strip() == 'Then hello world!'
        assert str(ie.value) == 'list index out of range'

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

            def filter_keyword_properties(keywords: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                return [{key: value for key, value in keyword.items() if key in ['label', 'kind']} for keyword in keywords]

            # partial match, keyword containing 'B'
            response = self._completion(client, lsp_fixture.datadir, ''''Feature:
    Scenario:
        B''')

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
            response = self._completion(client, lsp_fixture.datadir, '''Feature:
    Scenario:
        en''')
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
            unexpected_kinds = list(filter(lambda k: k != 14, map(lambda k: k.get('kind', None), items)))
            assert len(unexpected_kinds) == 0
            labels = list(map(lambda k: k.get('label', None), items))
            assert all([True if l is not None else False for l in labels])
            assert labels == ['Feature']

        def test_completion_steps(self, lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
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

                assert 'ask for value of variable ""' in labels
                assert 'spawn rate is "" user per second' in labels
                assert 'spawn rate is "" users per second' in labels
                assert 'a user of type "" with weight "" load testing ""' in labels

            response = self._completion(client, lsp_fixture.datadir, 'Given value')
            assert not response.get('isIncomplete', True)
            unexpected_kinds = list(filter(lambda s: s != 3, map(lambda s: s.get('kind', None), response.get('items', []))))
            assert len(unexpected_kinds) == 0

            labels = list(map(lambda s: s.get('label', None), response.get('items', [])))
            assert len(labels) > 0
            assert all([True if l is not None else False for l in labels])

            assert 'ask for value of variable ""' in labels
            assert 'value for variable "" is ""'

            response = self._completion(client, lsp_fixture.datadir, 'Given a user of')
            assert not response.get('isIncomplete', True)
            unexpected_kinds = list(filter(lambda s: s != 3, map(lambda s: s.get('kind', None), response.get('items', []))))
            assert len(unexpected_kinds) == 0

            labels = list(map(lambda s: s.get('label', None), response.get('items', [])))
            assert len(labels) > 0
            assert all([True if l is not None else False for l in labels])

            assert 'a user of type "" with weight "" load testing ""' in labels
            assert 'a user of type "" load testing ""' in labels

