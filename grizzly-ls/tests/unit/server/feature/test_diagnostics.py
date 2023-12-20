from typing import Any

from pygls.workspace import TextDocument
from pytest_mock import MockerFixture
from lsprotocol import types as lsp

from grizzly_ls.server.features.diagnostics import validate_gherkin
from grizzly_ls.model import Step

from tests.fixtures import LspFixture


def test_validate_gherkin(lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
    ls = lsp_fixture.server

    ls.language = 'en'

    # <!-- no language yet
    text_document = TextDocument(
        'file://test.feature',
        '''# language:
Feature:
    Scenario: test
''',
    )
    diagnostics = validate_gherkin(ls, text_document)

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
    diagnostics = validate_gherkin(ls, text_document)

    assert len(diagnostics) == 2

    # invalid language
    diagnostic = diagnostics[0]
    assert diagnostic.range == lsp.Range(
        start=lsp.Position(line=1, character=12),
        end=lsp.Position(line=1, character=16),
    )
    assert diagnostic.message == '"asdf" is not a valid language'
    assert diagnostic.severity == lsp.DiagnosticSeverity.Error
    assert diagnostic.code is None
    assert diagnostic.code_description is None
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None

    # wrong line
    diagnostic = diagnostics[1]
    assert diagnostic.range == lsp.Range(
        start=lsp.Position(line=1, character=0),
        end=lsp.Position(line=1, character=16),
    )
    assert diagnostic.message == '"# language:" should be on the first line'
    assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
    assert diagnostic.code is None
    assert diagnostic.code_description is None
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None
    # // -->

    # <!-- keyword language != specified language
    ls.language = 'sv'
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
    diagnostics = validate_gherkin(ls, text_document)

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
    assert diagnostic.source == ls.__class__.__name__
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
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None
    # // -->

    # <!-- step implementation not found
    ls.language = 'en'
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

    ls.steps.update({'then': [Step('then', 'this step actually exists!', func=noop)]})
    diagnostics = validate_gherkin(ls, text_document)

    assert len(diagnostics) == 2

    diagnostic = diagnostics[0]

    assert diagnostic.range == lsp.Range(
        start=lsp.Position(line=6, character=14),
        end=lsp.Position(line=6, character=36),
    )
    assert (
        diagnostic.message
        == 'No step implementation found for:\nGiven a step in the scenario'
    )
    assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
    assert diagnostic.code is None
    assert diagnostic.code_description is None
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None

    diagnostic = diagnostics[1]

    assert diagnostic.range == lsp.Range(
        start=lsp.Position(line=7, character=12),
        end=lsp.Position(line=7, character=48),
    )
    assert (
        diagnostic.message
        == 'No step implementation found for:\nAnd another expression with a "variable"'
    )
    assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
    assert diagnostic.code is None
    assert diagnostic.code_description is None
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None
    # // -->

    # <!-- "complex" document with no errors
    try:
        ls.language = 'sv'
        text_document = TextDocument(
            'file://test.feature',
            '''# language: sv
    # testspecifikation: https://test.nu/specifikation/T01
    Egenskap: T01
        """
        lite text
        bara
        """
        Scenario: test
            Givet en tabell
            # denna tabell mappar en nyckel med ett värde
            | nyckel | värde |
            | foo    | bar   |
            | bar    | foo   |

            Och följande fråga
            """
            SELECT key, value FROM [dbo].[tests]
            """

            Så producera ett dokument i formatet "json"
    ''',
        )

        ls.steps.update(
            {
                'then': [
                    Step('then', 'producera ett dokument i formatet "json"', func=noop),
                    Step('then', 'producera ett dokument i formatet "xml"', func=noop),
                    Step('then', 'producera ett dokument i formatet "docx"', func=noop),
                ],
                'given': [Step('given', 'en tabell', func=noop)],
                'step': [Step('step', 'följande fråga', func=noop)],
            }
        )
        diagnostics = validate_gherkin(ls, text_document)

        assert diagnostics == []
    finally:
        ls.language = 'en'
    # // -->
