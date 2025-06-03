import logging
from typing import Any
from itertools import product

from pygls.workspace import TextDocument
from lsprotocol import types as lsp
from _pytest.logging import LogCaptureFixture  # type: ignore

from grizzly_ls.server.features.diagnostics import validate_gherkin
from grizzly_ls.model import Step

from tests.fixtures import LspFixture


def test_validate_gherkin(lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
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
    diagnostic = list(diagnostics)[0]
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
    with caplog.at_level(logging.DEBUG):
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
    assert diagnostic.message == 'No step implementation found\nGiven a step in the scenario'
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
    assert diagnostic.message == 'No step implementation found\nAnd another expression with a "variable"'
    assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
    assert diagnostic.code is None
    assert diagnostic.code_description is None
    assert diagnostic.source == ls.__class__.__name__
    assert diagnostic.tags is None
    assert diagnostic.related_information is None
    assert diagnostic.data is None
    # // -->

    # <!-- freetext marker not closed
    ls.language = 'en'
    text_document = TextDocument(
        'file://test.feature',
        '''# language: en
Feature:
    """
    this is just a comment
    Scenario: test
        Then this step actually exists!
''',
    )

    diagnostics = validate_gherkin(ls, text_document)

    diagnostic = next(iter(diagnostics))

    assert diagnostic.message == 'Freetext marker is not closed'
    assert diagnostic.severity == lsp.DiagnosticSeverity.Error
    # // -->

    # <!-- "complex" document with no errors
    feature_file = lsp_fixture.datadir / 'features' / 'test.feature'
    included_feature_file_1 = lsp_fixture.datadir / 'features' / 'hello.feature'
    included_feature_file_2 = lsp_fixture.datadir / 'world.feature'

    feature_file.write_text(
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

        Scenario: inkluderat-1
            {% scenario "hello" feature="./hello.feature" %}

        Scenario: inkluderat-2
            {% scenario "world" "./hello.feature" %}

        Scenario: inkluderat-3
            {% scenario scenario="foo", feature="./hello.feature" %}

        Scenario: inkluderat-4
            {%  scenario  scenario="bar" ,   "./hello.feature" %}

        # Scenario: inactive
        #   {% scenario "hello", feature="../world.feature" %}

        Scenario: inkluderat-5
            {% scenario "world", feature="../world.feature" %}
    ''',
        encoding='utf-8',
    )

    included_feature_file_1.write_text(
        '''# language: sv
Egenskap: hello
    Scenario: hello
        Så producera ett dokument i formatet "xml"

    Scenario: world
        Så producera ett dokument i formatet "yaml"

    Scenario: foo
        Så producera en bild i formatet "gif"

    Scenario: bar
        Så producera en bild i formatet "png"
    ''',
        encoding='utf-8',
    )

    included_feature_file_2.write_text(
        '''# language: sv
Egenskap: hello
    Scenario: hello
        Så producera ett dokument i formatet "xml"

    Scenario: world
        Så producera ett dokument i formatet "yaml"
    ''',
        encoding='utf-8',
    )

    try:
        ls.language = 'sv'
        text_document = TextDocument(feature_file.as_uri())

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
        feature_file.unlink()
        included_feature_file_1.unlink()
        included_feature_file_2.unlink()
    # // -->


def test_validate_gherkin_scenario_tag(lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
    ls = lsp_fixture.server

    feature_file = lsp_fixture.datadir / 'features' / 'test_validate_gherkin_scenario_tag.feature'
    included_feature_file = lsp_fixture.datadir / 'features' / 'test_validate_gherkin_scenario_tag_include.feature'

    try:
        # <!-- jinja2 expression, not scenario tag -- ignored
        feature_file.write_text(
            '''Feature: test scenario tag
    Scenario: included
        {% hello %}
    ''',
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)
        assert diagnostics == []
        # // -->

        # <!-- scenario tag, no arguments
        feature_file.write_text(
            '''Feature: test scenario tag
    Scenario: included
        {% scenario %}
    ''',
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)
        assert len(diagnostics) == 2
        diagnostic = diagnostics[0]
        assert diagnostic.message == 'Scenario tag is invalid, could not find scenario argument'
        assert str(diagnostic.range) == '2:8-2:22'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error

        diagnostic = diagnostics[1]
        assert diagnostic.message == 'Scenario tag is invalid, could not find feature argument'
        assert str(diagnostic.range) == '2:8-2:22'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error
        # // -->

        # <!-- empty scenario and feature arguments
        feature_file.write_text(
            '''Feature: test scenario tag
    Scenario: included
        {% scenario "", feature="" %}
    ''',
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)
        assert len(diagnostics) == 2
        diagnostic = diagnostics[0]
        assert diagnostic.message == 'Feature argument is empty'
        assert str(diagnostic.range) == '2:33-2:33'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning

        diagnostic = diagnostics[1]
        assert diagnostic.message == 'Scenario argument is empty'
        assert str(diagnostic.range) == '2:21-2:21'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning
        # // -->

        # <!-- missing feature argument, scenario argument both as positional and named
        for argument in ['"foo"', 'scenario="foo"']:
            feature_file.write_text(
                f'''Feature: test scenario tag
    Scenario: included
        {{% scenario {argument} %}}
    ''',
                encoding='utf-8',
            )
            text_document = TextDocument(feature_file.as_posix())

            diagnostics = validate_gherkin(ls, text_document)
            assert len(diagnostics) == 1
            diagnostic = diagnostics[0]
            assert diagnostic.message == 'Scenario tag is invalid, could not find feature argument'
            end = len(argument) + 21 + 2
            assert str(diagnostic.range) == f'2:8-2:{end}'
            assert diagnostic.severity == lsp.DiagnosticSeverity.Error
        # // -->

        # <!-- specified feature file that does not exist
        for arg_scenario, arg_feature in product(
            ['"foo"', 'scenario="foo"'],
            [
                '"./test_validate_gherkin_scenario_tag_include.feature"',
                'feature="./test_validate_gherkin_scenario_tag_include.feature"',
            ],
        ):
            for prefix in [None, (lsp_fixture.datadir / 'features').as_posix()]:
                if prefix is not None:
                    arg_feature = arg_feature.replace('./', f'{prefix}/')

                feature_file.write_text(
                    f'''Feature: test scenario tag
        Scenario: included
            {{% scenario {arg_scenario}, {arg_feature} %}}
        ''',
                    encoding='utf-8',
                )
                text_document = TextDocument(feature_file.as_posix())

                included_feature_file.unlink(missing_ok=True)

                diagnostics = validate_gherkin(ls, text_document)

                assert len(diagnostics) == 1

                diagnostic = diagnostics[0]

                _, feature_file_name, _ = arg_feature.split('"', 3)

                assert diagnostic.message == f'Included feature file "{feature_file_name}" does not exist'

                included_feature_file.touch()

                diagnostics = validate_gherkin(ls, text_document)
                diagnostic = next(iter(diagnostics))

                assert diagnostic.message == f'Included feature file "{feature_file_name}" does not have any scenarios'

                included_feature_file.write_text('''Egenskap: test''', encoding='utf-8')

                diagnostics = validate_gherkin(ls, text_document)
                diagnostic = next(iter(diagnostics))

                assert diagnostic.message == 'Parser failure in state init\nNo feature found.'

                included_feature_file.write_text('''Feature: test''', encoding='utf-8')

                diagnostics = validate_gherkin(ls, text_document)
                diagnostic = next(iter(diagnostics))

                assert diagnostic.message == f'Scenario "foo" does not exist in included feature "{feature_file_name}"'

                included_feature_file.write_text(
                    '''Feature: test
Scenario: foo''',
                    encoding='utf-8',
                )

                diagnostics = validate_gherkin(ls, text_document)
                diagnostic = next(iter(diagnostics))

                assert diagnostic.message == f'Scenario "foo" in "{feature_file_name}" does not have any steps'

                included_feature_file.write_text(
                    '''Feature: test
Scenario: foo
    Given a step expression''',
                    encoding='utf-8',
                )

                with caplog.at_level(logging.DEBUG):
                    diagnostics = validate_gherkin(ls, text_document)

                assert diagnostics == []
        # // -->

        # <!-- scenario tag values argument
        feature_file.write_text(
            """Feature: test scenario tag
    Scenario: included
        {% scenario "include", feature="./test_validate_gherkin_scenario_tag_include.feature", foo="bar", bar="foo" %}
    """,
            encoding='utf-8',
        )

        included_feature_file = lsp_fixture.datadir / 'features' / 'test_validate_gherkin_scenario_tag_include.feature'
        included_feature_file.write_text(
            """Feature:
    Scenario: include
        Given a step expression
    """,
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)

        assert len(diagnostics) == 2

        diagnostic = diagnostics[0]
        assert diagnostic.message == 'Declared variable "foo" is not used in included scenario steps'
        assert str(diagnostic.range) == '2:95-2:104'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error

        diagnostic = diagnostics[1]
        assert diagnostic.message == 'Declared variable "bar" is not used in included scenario steps'
        assert str(diagnostic.range) == '2:106-2:115'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error

        included_feature_file.write_text(
            """Feature:
    Scenario: include
        Given a step expression named "{$ foo $}"
        And a step expression named "{$ baz $}"

""",
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)

        assert len(diagnostics) == 2

        diagnostic = diagnostics[0]
        assert diagnostic.message == 'Declared variable "bar" is not used in included scenario steps'
        assert str(diagnostic.range) == '2:106-2:115'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Error

        diagnostic = diagnostics[1]
        assert diagnostic.message == 'Scenario tag is missing variable "baz"'
        assert str(diagnostic.range) == '2:8-2:118'
        assert diagnostic.severity == lsp.DiagnosticSeverity.Warning

        included_feature_file.write_text(
            """Feature:
    Scenario: include
        Given a step expression named "{$ foo $}"
        And a step expression named "{$ bar $}"

""",
            encoding='utf-8',
        )
        text_document = TextDocument(feature_file.as_posix())

        diagnostics = validate_gherkin(ls, text_document)
        assert diagnostics == []
        # // -->
    finally:
        included_feature_file.unlink(missing_ok=True)
        feature_file.unlink(missing_ok=True)
