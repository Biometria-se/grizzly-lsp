import logging

from lsprotocol import types as lsp
from pygls.workspace import TextDocument

from _pytest.logging import LogCaptureFixture

from grizzly_ls.server.features.completion import complete_keyword, complete_step
from grizzly_ls.server.inventory import compile_inventory

from tests.fixtures import LspFixture
from tests.conftest import GRIZZLY_PROJECT
from tests.helpers import normalize_completion_item, normalize_completion_text_edit


def test_complete_keyword(lsp_fixture: LspFixture) -> None:
    ls = lsp_fixture.server
    ls.root_path = GRIZZLY_PROJECT
    compile_inventory(ls, 'project')

    text_document = TextDocument(
        uri='dummy.feature',
        source='',
    )

    null_position = lsp.Position(line=0, character=0)

    assert normalize_completion_item(
        complete_keyword(ls, None, null_position, text_document),
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
            complete_keyword(ls, None, null_position, text_document),
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
            complete_keyword(ls, None, null_position, text_document),
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
            complete_keyword(ls, None, null_position, text_document),
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
            complete_keyword(
                ls, 'EN', lsp.Position(line=0, character=2), text_document
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
        complete_keyword(ls, 'Giv', lsp.Position(line=0, character=4), text_document),
        lsp.CompletionItemKind.Keyword,
    ) == [
        'Given',
    ]


def test_complete_step(lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
    ls = lsp_fixture.server
    ls.root_path = GRIZZLY_PROJECT
    compile_inventory(ls, 'project')

    with caplog.at_level(logging.DEBUG):
        matched_steps = normalize_completion_item(
            complete_step(ls, 'Given', lsp.Position(line=0, character=6), 'variable'),
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
            complete_step(ls, 'Then', lsp.Position(line=0, character=5), 'save'),
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

        suggested_steps = complete_step(
            ls,
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
                suggested_step.label == 'save response metadata "hello" in variable ""'
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
            complete_step(ls, 'When', lsp.Position(line=0, character=4), None),
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
            complete_step(ls, 'When', lsp.Position(line=0, character=13), 'response '),
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
            complete_step(
                ls, 'When', lsp.Position(line=0, character=25), 'response fail request'
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
            complete_step(
                ls,
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
            complete_step(
                ls,
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

        actual_completed_steps = complete_step(
            ls, 'And', lsp.Position(line=0, character=20), 'repeat for "1" it'
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

        actual_completed_steps = complete_step(
            ls, 'And', lsp.Position(line=0, character=16), 'repeat for "1"'
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

        actual_completed_steps = complete_step(
            ls, 'And', lsp.Position(line=0, character=17), 'repeat for "1" '
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

        actual_completed_steps = complete_step(
            ls,
            'Then',
            lsp.Position(line=0, character=38),
            'parse date "{{ datetime.now() }}" ',
        )
        assert len(actual_completed_steps) == 1
        actual_completed_step = actual_completed_steps[0]
        assert (
            actual_completed_step.text_edit is not None
            and actual_completed_step.text_edit.new_text == 'and save in variable "$1"'
        )

        actual_completed_steps = complete_step(
            ls,
            'Then',
            lsp.Position(line=0, character=37),
            'parse date "{{ datetime.now() }}"',
        )
        assert len(actual_completed_steps) == 1
        actual_completed_step = actual_completed_steps[0]
        assert (
            actual_completed_step.text_edit is not None
            and actual_completed_step.text_edit.new_text == ' and save in variable "$1"'
        )