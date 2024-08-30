import sys
import logging

from pathlib import Path
from shutil import rmtree
from inspect import getsourcelines

from lsprotocol import types as lsp
from pygls.workspace import Workspace

from _pytest.logging import LogCaptureFixture

from grizzly_ls.server.features.definition import (
    get_step_definition,
    get_file_url_definition,
)
from grizzly_ls.model import Step
from tests.fixtures import LspFixture
from tests.conftest import GRIZZLY_PROJECT


def test_get_step_definition(lsp_fixture: LspFixture) -> None:
    ls = lsp_fixture.server

    text_document = lsp.TextDocumentIdentifier('file:///hello.feature')
    position = lsp.Position(line=0, character=0)
    params = lsp.DefinitionParams(text_document, position)

    assert get_step_definition(ls, params, '') is None
    assert get_step_definition(ls, params, 'Then ') is None

    def step_impl() -> None:  # <!-- lineno
        pass

    _, lineno = getsourcelines(step_impl)

    ls.steps.update(
        {
            'given': [
                Step('given', 'foobar', step_impl, 'todo'),
                Step('given', 'hello world!', step_impl, 'todo'),
            ]
        }
    )
    params.position.character = 5
    actual_definition = get_step_definition(ls, params, 'Given hello world!')

    assert actual_definition is not None
    assert actual_definition.target_uri == Path(__file__).as_uri()
    assert actual_definition.target_range == lsp.Range(
        start=lsp.Position(line=lineno, character=0),
        end=lsp.Position(line=lineno, character=0),
    )


def test_get_file_url_definition(lsp_fixture: LspFixture, caplog: LogCaptureFixture) -> None:
    ls = lsp_fixture.server
    ls.root_path = GRIZZLY_PROJECT
    ls.lsp._workspace = Workspace(ls.root_path.as_uri())

    test_feature_file = ls.root_path / 'features' / 'empty.feature'
    test_file = ls.root_path / 'features' / 'requests' / 'test.txt'
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.touch()

    test_feature_file_included = ls.root_path / 'features' / 'included.feature'
    test_feature_file_included.write_text(
        """Feature: test feature
    Background: common steps

    Scenario: world
        Then log message "boo"

    Scenario: hello
        Then log message "yay"

    Scenario: foo
        Then log messge "bar"
"""
    )

    def get_platform_uri(uri: str) -> str:
        # windows is case-insensitive, and drive letter can be different case...
        # and drive latters in uri's from LSP seems to be in lower-case...
        return uri.lower() if sys.platform == 'win32' else uri

    try:
        text_document = lsp.TextDocumentIdentifier(test_feature_file.as_uri())
        position = lsp.Position(line=0, character=0)
        params = lsp.DefinitionParams(text_document, position)

        # no files
        assert (
            get_file_url_definition(
                ls,
                params,
                'Then this is a variable "hello" and this is also a variable "world"',
            )
            == []
        )

        # `file://` in a "variable"
        position.character = 26
        actual_definitions = get_file_url_definition(
            ls,
            params,
            f'Then this is a variable "file://./requests/test.txt" and this is also a variable "$include::{test_file.as_uri()}$"',
        )  # .character =               ^- 26                    ^- 51

        assert len(actual_definitions) == 1
        actual_definition = actual_definitions[0]
        assert get_platform_uri(actual_definition.target_uri) == get_platform_uri(test_file.as_uri())
        assert actual_definition.target_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.target_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.origin_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=25),
            end=lsp.Position(line=0, character=51),
        )

        # `$include::file://..$` in a "variable"
        position.character = 95
        expression = f'Then this is a variable "file://./requests/test.txt" and this is also a variable "$include::{test_file.as_uri()}$"'
        actual_definitions = get_file_url_definition(
            ls,
            params,
            expression,
        )

        assert len(actual_definitions) == 1
        actual_definition = actual_definitions[0]
        assert get_platform_uri(actual_definition.target_uri) == get_platform_uri(test_file.as_uri())
        assert actual_definition.target_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.target_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.origin_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=92),
            end=lsp.Position(line=0, character=92 + len(test_file.as_uri())),
        )

        # classic (relative to grizzly requests directory)
        position.character = 16
        actual_definitions = get_file_url_definition(ls, params, 'Then send file "test.txt"')  # .character =                ^- 16   ^- 24

        assert len(actual_definitions) == 1
        actual_definition = actual_definitions[0]
        assert get_platform_uri(actual_definition.target_uri) == get_platform_uri(test_file.as_uri())
        assert actual_definition.target_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.target_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=0),
        )
        assert actual_definition.origin_selection_range == lsp.Range(
            start=lsp.Position(line=0, character=16),
            end=lsp.Position(line=0, character=24),
        )

        # {% scenario ... %}
        position.character = 30
        for path in ['', './', f'{test_feature_file_included.parent.as_posix()}/']:
            feature_argument = f'{path}included.feature'
            position = lsp.Position(line=0, character=32)
            params = lsp.DefinitionParams(text_document, position)
            with caplog.at_level(logging.DEBUG):
                actual_definitions = get_file_url_definition(ls, params, f'{{% scenario "hello", feature="{feature_argument}" %}}')

            assert len(actual_definitions) == 1
            actual_definition = actual_definitions[0]
            assert get_platform_uri(actual_definition.target_uri) == get_platform_uri(test_feature_file_included.as_uri())

            assert actual_definition.target_range == lsp.Range(
                start=lsp.Position(line=6, character=19),
                end=lsp.Position(line=6, character=19),
            )
            assert actual_definition.target_selection_range == lsp.Range(
                start=lsp.Position(line=6, character=19),
                end=lsp.Position(line=6, character=19),
            )
            assert actual_definition.origin_selection_range == lsp.Range(
                start=lsp.Position(line=0, character=30),
                end=lsp.Position(line=0, character=30 + len(feature_argument)),
            )
    finally:
        test_feature_file_included.unlink()
        rmtree(test_file.parent)
