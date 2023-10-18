import logging

from typing import Dict, List

import pytest
import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from lsprotocol import types as lsp
from behave.matchers import ParseMatcher

from tests.fixtures import LspFixture
from tests.conftest import GRIZZLY_PROJECT
from grizzly_ls import __version__
from grizzly_ls.server import Step
from grizzly_ls.server.inventory import compile_inventory


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
        ls = lsp_fixture.server
        try:
            ls.steps.clear()
            try:
                ls.language = 'dummy'
            except ValueError:
                pass

            ls.language = language

            assert ls.name == 'grizzly-ls'
            assert ls.version == __version__
            assert sorted(ls.keywords) == sorted(
                words.get('keywords', []),
            )
            assert sorted(ls.keywords_any) == sorted(words.get('keywords_any', []))
            assert sorted(ls.keywords_once) == sorted(words.get('keywords_once', []))

            assert isinstance(ls.logger, logging.Logger)
            assert ls.logger.name == 'grizzly_ls.server'
        finally:
            ls.language = 'en'

    def test_show_message(
        self,
        lsp_fixture: LspFixture,
        caplog: LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        ls = lsp_fixture.server
        show_message_mock = mocker.patch(
            'pygls.server.LanguageServer.show_message', return_value=None
        )

        message = 'implicit INFO level'
        with caplog.at_level(logging.INFO):
            ls.show_message(message)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Info
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'explicit INFO level'
        with caplog.at_level(logging.INFO):
            ls.show_message(message, lsp.MessageType.Info)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Info
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'ERROR level'
        with caplog.at_level(logging.ERROR):
            ls.show_message(message, lsp.MessageType.Error)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Error
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'WARNING level'
        with caplog.at_level(logging.WARNING):
            ls.show_message(message, lsp.MessageType.Warning)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Warning
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'DEBUG level'
        with caplog.at_level(logging.DEBUG):
            ls.show_message(message, lsp.MessageType.Debug)
        assert caplog.messages == [message]
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Debug
        )
        show_message_mock.reset_mock()
        caplog.clear()

        message = 'CRITICAL level'
        with caplog.at_level(logging.CRITICAL):
            ls.show_message(message, lsp.MessageType.Debug)
        assert caplog.messages == []
        show_message_mock.assert_called_once_with(
            message, msg_type=lsp.MessageType.Debug
        )
        show_message_mock.reset_mock()
        caplog.clear()

    def test__normalize_step_expression(
        self, lsp_fixture: LspFixture, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch('parse.Parser.__init__', return_value=None)
        ls = lsp_fixture.server

        ls.steps.clear()

        assert ls.steps == {}

        ls.root_path = GRIZZLY_PROJECT

        compile_inventory(ls)

        noop = lambda: None  # noqa: E731

        step = ParseMatcher(noop, 'hello world')

        assert ls._normalize_step_expression(step) == ['hello world']

        step = ParseMatcher(noop, 'hello "{world}"! how "{are:d}" you')

        assert ls._normalize_step_expression(step) == ['hello ""! how "" you']

        step = ParseMatcher(noop, 'you have "{count}" {grammar:UserGramaticalNumber}')

        assert sorted(ls._normalize_step_expression(step)) == sorted(
            [
                'you have "" users',
                'you have "" user',
            ]
        )

        step = ParseMatcher(
            noop, 'send from {from_node:MessageDirection} to {to_node:MessageDirection}'
        )

        assert sorted(ls._normalize_step_expression(step)) == sorted(
            [
                'send from client to server',
                'send from server to client',
            ]
        )

        assert sorted(
            ls._normalize_step_expression(
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
            ls._normalize_step_expression(
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
        actual = sorted(ls._normalize_step_expression(step))
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
            ls._normalize_step_expression(
                'python {condition:Condition} cool',
            )
        ) == sorted(
            [
                'python is cool',
                'python is not cool',
            ]
        )

        assert sorted(
            ls._normalize_step_expression(
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

        show_message_mock = mocker.patch.object(ls, 'show_message', autospec=True)

        with caplog.at_level(logging.ERROR):
            assert sorted(
                ls._normalize_step_expression(
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

    def test__find_help(self, lsp_fixture: LspFixture) -> None:
        ls = lsp_fixture.server

        ls.language = 'en'

        def noop() -> None:
            pass

        ls.steps = {
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

        assert ls._find_help('Then hello world') == 'this is the help for hello world'
        assert ls._find_help('Then hello') == 'this is the help for hello world'
        assert ls._find_help('asdfasdf') is None
        assert ls._find_help('And hello') == 'this is the help for hello world'
        assert (
            ls._find_help('And hello "world"')
            == 'this is the help for hello world parameterized'
        )
        assert ls._find_help('But foo') == 'this is the help for foo bar'
        assert (
            ls._find_help('But "foo" bar')
            == 'this is the help for foo bar parameterized'
        )

    def test__get_language_key(self, lsp_fixture: LspFixture) -> None:
        ls = lsp_fixture.server

        ls.language = 'sv'
        assert ls.get_language_key('Egenskap:') == 'feature'
        assert ls.get_language_key('Och') == 'step'
        assert ls.get_language_key('Givet') == 'given'
        assert ls.get_language_key('Scenariomall:') == 'scenario_outline'
        assert ls.get_language_key('När') == 'when'
        assert ls.get_language_key('Så') == 'then'
        assert ls.get_language_key('Exempel') == 'examples'
        assert ls.get_language_key('Bakgrund') == 'background'
        with pytest.raises(ValueError) as ve:
            ls.get_language_key('Feature')
        assert str(ve.value) == '"Feature" is not a valid keyword for "sv"'

        ls.language = 'en'
        assert ls.get_language_key('Feature') == 'feature'
        assert ls.get_language_key('And') == 'step'
        assert ls.get_language_key('Given') == 'given'
        assert ls.get_language_key('Scenario Template:') == 'scenario_outline'
        assert ls.get_language_key('When') == 'when'
        assert ls.get_language_key('Then') == 'then'
        assert ls.get_language_key('Examples') == 'examples'
        assert ls.get_language_key('Background') == 'background'
        with pytest.raises(ValueError) as ve:
            ls.get_language_key('Egenskap')
        assert str(ve.value) == '"Egenskap" is not a valid keyword for "en"'
