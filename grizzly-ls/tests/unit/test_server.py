import logging

from typing import Dict, Any, List
from pathlib import Path

import pytest
import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pygls.workspace import Workspace, TextDocument
from lsprotocol import types as lsp
from behave.matchers import ParseMatcher

from tests.fixtures import LspFixture
from tests.helpers import normalize_completion_item, normalize_completion_text_edit
from grizzly_ls import __version__
from grizzly_ls.server import Step


GRIZZLY_PROJECT = (
    Path(__file__) / '..' / '..' / '..' / '..' / 'tests' / 'project'
).resolve()


class TestGrizzlyLanguageServer:
    @pytest.mark.parametrize(
        'language,words',
        [
            (
                'en',
                {
                    'keywords': [
                        'Scenario',
                        'Scenario Outline',
                        'Scenario Template',
                        'Examples',
                        'Scenarios',
                        'And',
                        'But',
                    ],
                    'keywords_any': ['*', 'But', 'And'],
                    'keywords_once': ['Feature', 'Background'],
                },
            ),
            (
                'sv',
                {
                    'keywords': [
                        'Scenario',
                        'Abstrakt Scenario',
                        'Scenariomall',
                        'Exempel',
                        'Och',
                        'Men',
                    ],
                    'keywords_any': ['*', 'Men', 'Och'],
                    'keywords_once': ['Egenskap', 'Bakgrund'],
                },
            ),
            (
                'de',
                {
                    'keywords': [
                        'Szenario',
                        'Szenariogrundriss',
                        'Beispiele',
                        'Und',
                        'Aber',
                    ],
                    'keywords_any': ['*', 'Und', 'Aber'],
                    'keywords_once': ['Grundlage', u'Funktionalit\xe4t'],
                },
            ),
        ],
    )
    def test___init__(
        self, language: str, words: Dict[str, List[str]], lsp_fixture: LspFixture
    ) -> None:
        server = lsp_fixture.server
        try:
            server.steps.clear()
            try:
                server.language = 'dummy'
            except ValueError:
                pass

            server.language = language

            assert server.name == 'grizzly-ls'
            assert server.version == __version__
            assert sorted(server.keywords) == sorted(
                words.get('keywords', []),
            )
            assert sorted(server.keywords_any) == sorted(words.get('keywords_any', []))
            assert sorted(server.keywords_once) == sorted(
                words.get('keywords_once', [])
            )

            assert isinstance(server.logger, logging.Logger)
            assert server.logger.name == 'grizzly_ls.server'
        finally:
            server.language = 'en'

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
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Info
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'explicit INFO level'
        with caplog.at_level(logging.INFO):
            server.show_message(message, lsp.MessageType.Info)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Info
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'ERROR level'
        with caplog.at_level(logging.ERROR):
            server.show_message(message, lsp.MessageType.Error)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Error
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'WARNING level'
        with caplog.at_level(logging.WARNING):
            server.show_message(message, lsp.MessageType.Warning)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Warning
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'DEBUG level'
        with caplog.at_level(logging.DEBUG):
            server.show_message(message, lsp.MessageType.Debug)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Debug
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'CRITICAL level'
        with caplog.at_level(logging.CRITICAL):
            server.show_message(message, lsp.MessageType.Debug)
        assert caplog.messages == []
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Debug
        )
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
        server = lsp_fixture.server
        server.root_path = GRIZZLY_PROJECT
        server._compile_inventory('project')

        text_document = TextDocument(
            uri='dummy.feature',
            source='',
        )

        null_position = lsp.Position(line=0, character=0)

        assert normalize_completion_item(
            server._complete_keyword(None, null_position, text_document),
            lsp.CompletionItemKind.Keyword,
        ) == [
            'Feature',
        ]

        text_document = TextDocument(
            uri='dummy.feature',
            source='Feature:',
        )

        assert sorted(
            normalize_completion_item(
                server._complete_keyword(None, null_position, text_document),
                lsp.CompletionItemKind.Keyword,
            )
        ) == sorted(
            [
                'Background',
                'Scenario',
                'Scenario Outline',
                'Scenario Template',
            ]
        )

        text_document = TextDocument(
            uri='dummy.feature',
            source='''Feature:
    Scenario:
''',
        )

        assert sorted(
            normalize_completion_item(
                server._complete_keyword(None, null_position, text_document),
                lsp.CompletionItemKind.Keyword,
            )
        ) == sorted(
            [
                'And',
                'Background',
                'But',
                'Given',
                'Scenario',
                'Scenario Outline',
                'Scenario Template',
                'Then',
                'When',
                'Examples',
                'Scenarios',
            ]
        )

        text_document = TextDocument(
            uri='dummy.feature',
            source='''Feature:
    Background:
        Given a bunch of stuff
    Scenario:
''',
        )

        assert sorted(
            normalize_completion_item(
                server._complete_keyword(None, null_position, text_document),
                lsp.CompletionItemKind.Keyword,
            )
        ) == sorted(
            [
                'And',
                'But',
                'Given',
                'Scenario',
                'Scenario Outline',
                'Scenario Template',
                'Examples',
                'Scenarios',
                'Then',
                'When',
            ]
        )

        assert sorted(
            normalize_completion_item(
                server._complete_keyword(
                    'EN', lsp.Position(line=0, character=2), text_document
                ),
                lsp.CompletionItemKind.Keyword,
            )
        ) == sorted(
            [
                'Given',
                'Scenario',
                'Scenario Template',
                'Scenario Outline',
                'Scenarios',
                'Then',
                'When',
            ]
        )

        assert normalize_completion_item(
            server._complete_keyword(
                'Giv', lsp.Position(line=0, character=4), text_document
            ),
            lsp.CompletionItemKind.Keyword,
        ) == [
            'Given',
        ]

    def test__complete_step(
        self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
    ) -> None:
        server = lsp_fixture.server
        server.root_path = GRIZZLY_PROJECT
        server._compile_inventory('project')

        with caplog.at_level(logging.DEBUG):
            matched_steps = normalize_completion_item(
                server._complete_step(
                    'Given', lsp.Position(line=0, character=6), 'variable'
                ),
                lsp.CompletionItemKind.Function,
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
                server._complete_step(
                    'Then', lsp.Position(line=0, character=5), 'save'
                ),
                lsp.CompletionItemKind.Function,
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
                'Then',
                lsp.Position(line=0, character=35),
                'save response metadata "hello"',
            )
            matched_steps = normalize_completion_item(
                suggested_steps, lsp.CompletionItemKind.Function
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
                        suggested_step.text_edit is not None
                        and suggested_step.text_edit.new_text
                        == ' that matches "$1" in variable "$2"'
                    )
                elif (
                    suggested_step.label
                    == 'save response metadata "hello" in variable ""'
                ):
                    assert (
                        suggested_step.text_edit is not None
                        and suggested_step.text_edit.new_text == ' in variable "$1"'
                    )
                else:
                    raise AssertionError(
                        f'"{suggested_step.label}" was an unexpected suggested step'
                    )

            matched_steps = normalize_completion_item(
                server._complete_step('When', lsp.Position(line=0, character=4), None),
                lsp.CompletionItemKind.Function,
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
                server._complete_step(
                    'When', lsp.Position(line=0, character=13), 'response '
                ),
                lsp.CompletionItemKind.Function,
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
                server._complete_step(
                    'When', lsp.Position(line=0, character=25), 'response fail request'
                ),
                lsp.CompletionItemKind.Function,
            )

            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
                'response metadata "" is not "" fail request',
                'response metadata "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step(
                    'When',
                    lsp.Position(line=0, character=39),
                    'response payload "" is fail request',
                ),
                lsp.CompletionItemKind.Function,
            )

            for expected_step in [
                'response payload "" is not "" fail request',
                'response payload "" is "" fail request',
            ]:
                assert expected_step in matched_steps

            matched_steps = normalize_completion_item(
                server._complete_step(
                    'Given',
                    lsp.Position(line=0, character=50),
                    'a user of type "RestApi" with weight "1" load',
                ),
                lsp.CompletionItemKind.Function,
            )

            assert len(matched_steps) == 1
            assert (
                matched_steps[0]
                == 'a user of type "RestApi" with weight "1" load testing ""'
            )

            actual_completed_steps = server._complete_step(
                'And', lsp.Position(line=0, character=20), 'repeat for "1" it'
            )

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                lsp.CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_text_edit = normalize_completion_text_edit(
                actual_completed_steps, lsp.CompletionItemKind.Function
            )

            assert sorted(matched_text_edit) == sorted(['iteration', 'iterations'])

            actual_completed_steps = server._complete_step(
                'And', lsp.Position(line=0, character=16), 'repeat for "1"'
            )

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                lsp.CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_text_edit = normalize_completion_text_edit(
                actual_completed_steps, lsp.CompletionItemKind.Function
            )

            assert sorted(matched_text_edit) == sorted([' iteration', ' iterations'])

            actual_completed_steps = server._complete_step(
                'And', lsp.Position(line=0, character=17), 'repeat for "1" '
            )

            matched_steps = normalize_completion_item(
                actual_completed_steps,
                lsp.CompletionItemKind.Function,
            )

            assert sorted(matched_steps) == sorted(
                ['repeat for "1" iterations', 'repeat for "1" iteration']
            )

            matched_text_edit = normalize_completion_text_edit(
                actual_completed_steps, lsp.CompletionItemKind.Function
            )

            assert sorted(matched_text_edit) == sorted(['iteration', 'iterations'])

            actual_completed_steps = server._complete_step(
                'Then',
                lsp.Position(line=0, character=38),
                'parse date "{{ datetime.now() }}" ',
            )
            assert len(actual_completed_steps) == 1
            actual_completed_step = actual_completed_steps[0]
            assert (
                actual_completed_step.text_edit is not None
                and actual_completed_step.text_edit.new_text
                == 'and save in variable "$1"'
            )

            actual_completed_steps = server._complete_step(
                'Then',
                lsp.Position(line=0, character=37),
                'parse date "{{ datetime.now() }}"',
            )
            assert len(actual_completed_steps) == 1
            actual_completed_step = actual_completed_steps[0]
            assert (
                actual_completed_step.text_edit is not None
                and actual_completed_step.text_edit.new_text
                == ' and save in variable "$1"'
            )

    def test__normalize_step_expression(
        self, lsp_fixture: LspFixture, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch('parse.Parser.__init__', return_value=None)
        server = lsp_fixture.server

        server.steps.clear()

        assert server.steps == {}

        server.root_path = GRIZZLY_PROJECT

        server._compile_inventory('project')

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

        server.steps.clear()

        assert server.steps == {}

        server.root_path = GRIZZLY_PROJECT.resolve()

        with caplog.at_level(logging.INFO, 'grizzly_ls.server'):
            server._compile_inventory('project')

        assert len(caplog.messages) == 1

        assert not server.steps == {}
        assert len(server.normalizer.custom_types.keys()) >= 8

        keywords = list(server.steps.keys())

        for keyword in ['given', 'then', 'when']:
            assert keyword in keywords

    def test__compile_keyword_inventory(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        server.steps.clear()

        assert server.steps == {}

        # create pre-requisites
        server.root_path = GRIZZLY_PROJECT
        server._compile_inventory('project')

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

        mocker.patch.object(server.lsp, '_workspace', Workspace(''))
        mocker.patch(
            'tests.unit.test_server.Workspace.get_text_document',
            return_value=TextDocument(
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
                'file://test.feature', lsp.Position(line=0, character=0)
            ).strip()
            == 'Feature:'
        )
        assert (
            server._current_line(
                'file://test.feature', lsp.Position(line=1, character=543)
            ).strip()
            == 'Scenario: test'
        )
        assert (
            server._current_line(
                'file://test.feature', lsp.Position(line=2, character=435)
            ).strip()
            == 'Then hello world!'
        )
        assert (
            server._current_line(
                'file://test.feature', lsp.Position(line=3, character=534)
            ).strip()
            == 'But foo bar'
        )

        with pytest.raises(IndexError) as ie:
            assert (
                server._current_line(
                    'file://test.feature', lsp.Position(line=10, character=10)
                ).strip()
                == 'Then hello world!'
            )
        assert str(ie.value) == 'list index out of range'

    def test__find_help(self, lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
        server = lsp_fixture.server

        server.language = 'en'

        def noop() -> None:
            pass

        server.steps = {
            'then': [
                Step('Then', 'hello world', noop, 'this is the help for hello world'),
            ],
            'step': [
                Step(
                    'And',
                    'hello ""',
                    noop,
                    'this is the help for hello world parameterized',
                ),
                Step('But', 'foo bar', noop, 'this is the help for foo bar'),
                Step(
                    'But', '"" bar', noop, 'this is the help for foo bar parameterized'
                ),
            ],
        }

        assert (
            server._find_help('Then hello world') == 'this is the help for hello world'
        )
        assert server._find_help('Then hello') == 'this is the help for hello world'
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

    def test__validate_gherkin(
        self, lsp_fixture: LspFixture, mocker: MockerFixture
    ) -> None:
        server = lsp_fixture.server

        server.language = 'en'

        # <!-- no language yet
        text_document = TextDocument(
            'file://test.feature',
            '''# language:
Feature:
    Scenario: test
''',
        )
        diagnostics = server._validate_gherkin(text_document)

        assert diagnostics == []
        # // -->

        # <!-- language invalid + wrong line
        text_document = TextDocument(
            'file://test.feature',
            '''
# language: asdf
Feature:
    """
    this is just a comment
    """
    Scenario: test
''',
        )
        diagnostics = server._validate_gherkin(text_document)

        assert len(diagnostics) == 2

        # invalid language
        diagnostic = diagnostics[0]
        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=1, character=12),
            end=lsp.Position(line=1, character=16),
        )
        assert diagnostic.message == 'asdf is not a valid language'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None

        # wrong line
        diagnostic = diagnostics[1]
        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=1, character=0),
            end=lsp.Position(line=1, character=16),
        )
        assert diagnostic.message == '# language: should be on the first line'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None
        # // -->

        # <!-- keyword language != specified language
        server.language = 'sv'
        text_document = TextDocument(
            'file://test.feature',
            '''# language: sv
Feature:
    """
    this is just a comment
    """
    Scenario: test
''',
        )
        diagnostics = server._validate_gherkin(text_document)

        assert len(diagnostics) == 2

        diagnostic = diagnostics[0]
        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=1, character=0),
            end=lsp.Position(line=1, character=7),
        )
        assert diagnostic.message == '"Feature" is not a valid keyword in Swedish'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None

        diagnostic = diagnostics[1]
        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=1, character=0),
            end=lsp.Position(line=1, character=7),
        )
        assert diagnostic.message == 'Parser failure in state init\nNo feature found.'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None
        # // -->

        # <!-- step implementation not found
        server.language = 'en'
        text_document = TextDocument(
            'file://test.feature',
            '''# language: en
Feature:
    """
    this is just a comment
    """
    Scenario: test
        Given a step in the scenario
        And another expression with a "variable"

        Then this step actually exists!
''',
        )

        def noop(*args: Any, **kwargs: Any) -> None:
            return None

        server.steps.update(
            {'then': [Step('then', 'this step actually exists!', func=noop)]}
        )
        diagnostics = server._validate_gherkin(text_document)

        assert len(diagnostics) == 2

        diagnostic = diagnostics[0]

        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=6, character=14),
            end=lsp.Position(line=6, character=35),
        )
        assert (
            diagnostic.message
            == 'No step implementation found for:\nGiven a step in the scenario'
        )
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None

        diagnostic = diagnostics[1]

        assert diagnostic.range == lsp.Range(
            start=lsp.Position(line=7, character=12),
            end=lsp.Position(line=7, character=47),
        )
        assert (
            diagnostic.message
            == 'No step implementation found for:\nAnd another expression with a "variable"'
        )
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
        assert diagnostic.code is None
        assert diagnostic.code_description is None
        assert diagnostic.source == server.__class__.__name__
        assert diagnostic.tags is None
        assert diagnostic.related_information is None
        assert diagnostic.data is None
        # // -->

    def test__get_step_definition(self, lsp_fixture: LspFixture) -> None:
        server = lsp_fixture.server

        position = lsp.Position(line=0, character=0)

        assert server._get_step_definition(position, '') is None
        assert server._get_step_definition(position, 'Then ') is None
