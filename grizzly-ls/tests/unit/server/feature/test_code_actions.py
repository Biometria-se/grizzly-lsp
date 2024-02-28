from typing import List
from pathlib import Path

from pygls.workspace import TextDocument
from lsprotocol import types as lsp
from pytest_mock import MockerFixture
from grizzly_ls.server.features.code_actions import (
    quick_fix_no_step_impl,
    quick_fix_lang_not_valid,
    quick_fix_lang_wrong_line,
    generate_quick_fixes,
)
from grizzly_ls.constants import (
    MARKER_NO_STEP_IMPL,
    MARKER_LANG_NOT_VALID,
    MARKER_LANG_WRONG_LINE,
    MARKER_LANGUAGE,
)

from tests.fixtures import LspFixture
from tests.conftest import GRIZZLY_PROJECT


def test_quick_fix_no_step_impl(lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
    ls = lsp_fixture.server
    ls.root_path = GRIZZLY_PROJECT
    expected_quick_fix_file = GRIZZLY_PROJECT / 'steps' / 'steps.py'

    feature_file = lsp_fixture.datadir / 'features' / 'test_quick_fix_no_step_impl.feature'

    text_document = TextDocument(feature_file.as_uri())

    try:
        # <!-- "And"
        feature_file.write_text(
            """Given foobar
"""
        )
        diagnostic = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=1, character=0),
                end=lsp.Position(line=1, character=0),
            ),
            message=f'{MARKER_NO_STEP_IMPL}:\nAnd hello world',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )

        # no template
        try:
            del ls.client_settings['quick_fix']
        except KeyError:
            pass

        assert quick_fix_no_step_impl(ls, diagnostic, text_document) is None

        ls.client_settings.update({'quick_fix': {'step_impl_template': "@{keyword}(u'{expression}')"}})

        # no quick fix file
        ls.root_path = Path('/tmp/asdf')
        assert quick_fix_no_step_impl(ls, diagnostic, text_document) is None

        # all good
        ls.root_path = GRIZZLY_PROJECT

        quick_fix = quick_fix_no_step_impl(ls, diagnostic, text_document)
        assert quick_fix is not None

        assert quick_fix.title == 'Create step implementation'
        assert quick_fix.kind == lsp.CodeActionKind.QuickFix
        assert quick_fix.diagnostics == [diagnostic]
        assert quick_fix.command == lsp.Command('Rebuild step inventory', 'grizzly.server.inventory.rebuild')

        actual_edit = quick_fix.edit
        assert isinstance(actual_edit, lsp.WorkspaceEdit)
        assert actual_edit.changes is not None

        actual_changes = actual_edit.changes.get(expected_quick_fix_file.as_uri(), None)
        assert actual_changes is not None
        assert len(actual_changes) == 1
        actual_text_edit = actual_changes[0]
        assert (
            actual_text_edit.new_text
            == '''
@given(u'hello world')
def step_impl(context: Context) -> None:
    raise NotImplementedError('no step implementation')
'''
        )

        source = expected_quick_fix_file.read_text().splitlines()
        expected_position = lsp.Position(line=len(source), character=0)

        assert actual_text_edit.range == lsp.Range(start=expected_position, end=expected_position)
        # // -->

        # <!-- Given
        diagnostic = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
            message=f'{MARKER_NO_STEP_IMPL}:\nGiven a whole lot of cash',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )

        ls.client_settings.update({'quick_fix': {'step_impl_template': "@step({keyword}, en=u'{expression}')"}})

        quick_fix = quick_fix_no_step_impl(ls, diagnostic, text_document)
        assert quick_fix is not None

        assert quick_fix.title == 'Create step implementation'
        assert quick_fix.kind == lsp.CodeActionKind.QuickFix
        assert quick_fix.diagnostics == [diagnostic]
        assert quick_fix.command == lsp.Command('Rebuild step inventory', 'grizzly.server.inventory.rebuild')

        actual_edit = quick_fix.edit
        assert isinstance(actual_edit, lsp.WorkspaceEdit)
        assert actual_edit.changes is not None

        actual_changes = actual_edit.changes.get(expected_quick_fix_file.as_uri(), None)
        assert actual_changes is not None
        assert len(actual_changes) == 1
        actual_text_edit = actual_changes[0]
        assert (
            actual_text_edit.new_text
            == '''
@step(given, en=u'a whole lot of cash')
def step_impl(context: Context) -> None:
    raise NotImplementedError('no step implementation')
'''
        )

        source = expected_quick_fix_file.read_text().splitlines()
        expected_position = lsp.Position(line=len(source), character=0)

        assert actual_text_edit.range == lsp.Range(start=expected_position, end=expected_position)
        # // -->

        # <!-- no a valid gherkin expression
        diagnostic = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
            message=f'{MARKER_NO_STEP_IMPL}:\nIf',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )

        assert quick_fix_no_step_impl(ls, diagnostic, text_document) is None
        # // -->

        # <!-- with arguments
        mocker.patch(
            'random_word.RandomWords.get_random_word',
            return_value='foobar',
        )
        diagnostic = lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
            message=f'{MARKER_NO_STEP_IMPL}:\nGiven a "book" with "100" pages',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )

        quick_fix = quick_fix_no_step_impl(ls, diagnostic, text_document)
        assert quick_fix is not None

        assert quick_fix.title == 'Create step implementation'
        assert quick_fix.kind == lsp.CodeActionKind.QuickFix
        assert quick_fix.diagnostics == [diagnostic]
        assert quick_fix.command == lsp.Command('Rebuild step inventory', 'grizzly.server.inventory.rebuild')

        actual_edit = quick_fix.edit
        assert isinstance(actual_edit, lsp.WorkspaceEdit)
        assert actual_edit.changes is not None

        actual_changes = actual_edit.changes.get(expected_quick_fix_file.as_uri(), None)
        assert actual_changes is not None
        assert len(actual_changes) == 1
        actual_text_edit = actual_changes[0]
        assert (
            actual_text_edit.new_text
            == '''
@step(given, en=u'a "{book}" with "{foobar}" pages')
def step_impl(context: Context, book: str, foobar: str) -> None:
    raise NotImplementedError('no step implementation')
'''
        )

        source = expected_quick_fix_file.read_text().splitlines()
        expected_position = lsp.Position(line=len(source), character=0)

        assert actual_text_edit.range == lsp.Range(start=expected_position, end=expected_position)
        # // -->

        # <!-- error...
        mocker.patch.object(ls, 'get_language_key', side_effect=ValueError)

        assert quick_fix_no_step_impl(ls, diagnostic, text_document) is None
        # // -->
    finally:
        feature_file.unlink()


def test_quick_fix_lang_not_valid() -> None:
    text_document = TextDocument(uri='file:///test.feature', source='')

    # <!-- default to 'en'
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        ),
        message=f'"huggabugga" {MARKER_LANG_NOT_VALID}',
        severity=lsp.DiagnosticSeverity.Warning,
        source='Dummy',
    )

    quick_fix = quick_fix_lang_not_valid(text_document, diagnostic)

    assert quick_fix is not None
    assert len(quick_fix) == 1
    actual_edit = quick_fix[0].edit
    assert actual_edit is not None
    actual_changes = actual_edit.changes
    assert actual_changes is not None
    assert len(actual_changes) == 1
    actual_text_edits = actual_changes.get('file:///test.feature', None)
    assert actual_text_edits is not None
    assert len(actual_text_edits) == 1
    assert actual_text_edits[0].new_text == 'en'
    # // -->

    # <!-- long typed name to short
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        ),
        message=f'"swedish" {MARKER_LANG_NOT_VALID}',
        severity=lsp.DiagnosticSeverity.Warning,
        source='Dummy',
    )

    quick_fix = quick_fix_lang_not_valid(text_document, diagnostic)

    assert quick_fix is not None
    assert len(quick_fix) == 1
    actual_edit = quick_fix[0].edit
    assert actual_edit is not None
    actual_changes = actual_edit.changes
    assert actual_changes is not None
    assert len(actual_changes) == 1
    actual_text_edits = actual_changes.get('file:///test.feature', None)
    assert actual_text_edits is not None
    assert len(actual_text_edits) == 1
    assert actual_text_edits[0].new_text == 'sv'
    # // -->

    # <!-- long typed native to short
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        ),
        message=f'"Svenska" {MARKER_LANG_NOT_VALID}',
        severity=lsp.DiagnosticSeverity.Warning,
        source='Dummy',
    )

    quick_fix = quick_fix_lang_not_valid(text_document, diagnostic)

    assert quick_fix is not None
    assert len(quick_fix) == 1
    actual_edit = quick_fix[0].edit
    assert actual_edit is not None
    actual_changes = actual_edit.changes
    assert actual_changes is not None
    assert len(actual_changes) == 1
    actual_text_edits = actual_changes.get('file:///test.feature', None)
    assert actual_text_edits is not None
    assert len(actual_text_edits) == 1
    assert actual_text_edits[0].new_text == 'sv'
    # // -->

    # <!-- closes match
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        ),
        message=f'"Cyrl" {MARKER_LANG_NOT_VALID}',
        severity=lsp.DiagnosticSeverity.Warning,
        source='Dummy',
    )

    quick_fix = quick_fix_lang_not_valid(text_document, diagnostic)

    assert quick_fix is not None
    assert len(quick_fix) == 1
    actual_edit = quick_fix[0].edit
    assert actual_edit is not None
    actual_changes = actual_edit.changes
    assert actual_changes is not None
    assert len(actual_changes) == 1
    actual_text_edits = actual_changes.get('file:///test.feature', None)
    assert actual_text_edits is not None
    assert len(actual_text_edits) == 1
    assert actual_text_edits[0].new_text == 'sr-Cyrl'
    # // -->


def test_quick_fix_lang_wrong_line() -> None:
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=2, character=0),
            end=lsp.Position(line=2, character=14),
        ),
        message=f'"{MARKER_LANGUAGE}" {MARKER_LANG_WRONG_LINE}',
        severity=lsp.DiagnosticSeverity.Warning,
        source='Dummy',
    )

    # <!-- unable to move text around
    text_document = TextDocument(
        uri='file:///test.feature',
        source='',
    )

    assert quick_fix_lang_wrong_line(text_document, diagnostic) is None
    # // -->

    text_document = TextDocument(
        uri='file:///test.feature',
        source='''
Feature: hello
# language: en
    Scenario: test
        Given sure
''',
    )

    quick_fix = quick_fix_lang_wrong_line(text_document, diagnostic)
    assert quick_fix is not None
    actual_edit = quick_fix.edit
    assert actual_edit is not None
    actual_changes = actual_edit.changes
    assert actual_changes is not None
    assert len(actual_changes) == 1
    actual_text_edits = actual_changes.get('file:///test.feature', None)
    assert actual_text_edits is not None
    assert len(actual_text_edits) == 1
    assert (
        actual_text_edits[0].new_text
        == '''# language: en

Feature: hello
    Scenario: test
        Given sure'''
    )


def test_generate_quick_fixes(lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
    ls = lsp_fixture.server
    ls.root_path = GRIZZLY_PROJECT

    diagnostics: List[lsp.Diagnostic] = []

    quick_fix_no_step_impl_mock = mocker.patch('grizzly_ls.server.features.code_actions.quick_fix_no_step_impl')
    quick_fix_lang_not_valid_mock = mocker.patch('grizzly_ls.server.features.code_actions.quick_fix_lang_not_valid')
    quick_fix_lang_wrong_line_mock = mocker.patch('grizzly_ls.server.features.code_actions.quick_fix_lang_wrong_line')

    text_document = TextDocument(
        uri='file:///test.feature',
        source='''
Feature: hello
# language: en
    Scenario: test
        Given sure
''',
    )

    # <!-- no quick fixes
    assert generate_quick_fixes(ls, text_document, []) is None
    quick_fix_no_step_impl_mock.assert_not_called()
    quick_fix_lang_not_valid_mock.assert_not_called()
    quick_fix_lang_wrong_line_mock.assert_not_called()
    # // -->

    # <!-- all the quick fixes
    # language wrong line
    diagnostics.append(
        lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=2, character=0),
                end=lsp.Position(line=2, character=14),
            ),
            message=f'"{MARKER_LANGUAGE}" {MARKER_LANG_WRONG_LINE}',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )
    )

    # language invalid
    diagnostics.append(
        lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
            message=f'"en-" {MARKER_LANG_NOT_VALID}',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )
    )

    # no step implementation
    diagnostics.append(
        lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            ),
            message=f'{MARKER_NO_STEP_IMPL}:\nGiven a "book" with "100" pages',
            severity=lsp.DiagnosticSeverity.Warning,
            source='Dummy',
        )
    )

    quick_fixes = generate_quick_fixes(ls, text_document, diagnostics)
    assert quick_fixes is not None
    assert len(quick_fixes) == 3
    quick_fix_no_step_impl_mock.assert_called_once_with(ls, diagnostics[2], text_document)
    quick_fix_lang_wrong_line_mock.assert_called_once_with(text_document, diagnostics[0])
    quick_fix_lang_not_valid_mock.assert_called_once_with(text_document, diagnostics[1])
    # // -->
