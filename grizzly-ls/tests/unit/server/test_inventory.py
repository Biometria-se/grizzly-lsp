import logging

import pytest

from pytest_mock import MockerFixture
from _pytest.logging import LogCaptureFixture

from grizzly_ls.server.inventory import (
    compile_inventory,
    create_step_normalizer,
)

from tests.fixtures import LspFixture
from tests.conftest import GRIZZLY_PROJECT
from tests.helpers import (
    parse_with_pattern_and_vector,
    parse_with_pattern,
    parse_enum_indirect,
    parse_with_pattern_error,
    DummyEnum,
    DummyEnumNoFromString,
    DummyEnumNoFromStringType,
)


def test_create_normalizer(mocker: MockerFixture) -> None:
    namespace = 'grizzly_ls.server.inventory'

    mocker.patch(
        f'{namespace}.ParseMatcher.custom_types',
        {},  # pyright: ignore[reportUnknownArgumentType]
    )

    normalizer = create_step_normalizer()
    assert normalizer.custom_types == {}

    mocker.patch(
        f'{namespace}.ParseMatcher.custom_types',
        {
            'WithPatternAndVector': parse_with_pattern_and_vector,
            'WithPattern': parse_with_pattern,
            'EnumIndirect': parse_enum_indirect,
            'EnumDirect': DummyEnum.from_string,
        },
    )
    normalizer = create_step_normalizer()

    assert list(sorted(normalizer.custom_types.keys())) == sorted(
        [
            'WithPatternAndVector',
            'WithPattern',
            'EnumIndirect',
            'EnumDirect',
        ]
    )

    with_pattern_and_vector = normalizer.custom_types.get('WithPatternAndVector', None)

    assert with_pattern_and_vector is not None
    assert (
        not with_pattern_and_vector.permutations.x
        and with_pattern_and_vector.permutations.y
    )
    assert sorted(with_pattern_and_vector.replacements) == sorted(
        ['bar', 'hello', 'foo', 'world']
    )

    with_pattern = normalizer.custom_types.get('WithPattern', None)

    assert with_pattern is not None
    assert not with_pattern.permutations.x and not with_pattern.permutations.y
    assert sorted(with_pattern.replacements) == sorted(['alice', 'bob'])

    enum_indirect = normalizer.custom_types.get('EnumIndirect', None)
    assert enum_indirect is not None
    assert enum_indirect.permutations.x and enum_indirect.permutations.y
    assert sorted(enum_indirect.replacements) == sorted(
        ['client_server', 'server_client']
    )

    enum_direct = normalizer.custom_types.get('EnumDirect', None)
    assert enum_direct is not None
    assert not enum_direct.permutations.x and not enum_direct.permutations.y
    assert sorted(enum_direct.replacements) == sorted(['hello', 'world', 'foo', 'bar'])

    mocker.patch(
        f'{namespace}.ParseMatcher.custom_types',
        {
            'WithPattern': parse_with_pattern_error,
        },
    )

    with pytest.raises(ValueError) as ve:
        create_step_normalizer()
    assert (
        str(ve.value)
        == 'could not extract pattern from "@parse.with_pattern(\'\')" for custom type WithPattern'
    )

    mocker.patch(
        f'{namespace}.ParseMatcher.custom_types',
        {
            'EnumError': DummyEnumNoFromString.magic,
        },
    )

    create_step_normalizer()

    mocker.patch(
        f'{namespace}.ParseMatcher.custom_types',
        {
            'EnumError': DummyEnumNoFromStringType.from_string,
        },
    )

    with pytest.raises(ValueError) as ve:
        create_step_normalizer()
    assert (
        str(ve.value)
        == 'could not find the type that from_string method for custom type EnumError returns'
    )


def test_compile_inventory(
    lsp_fixture: LspFixture, caplog: LogCaptureFixture, mocker: MockerFixture
) -> None:
    ls = lsp_fixture.server

    ls.steps.clear()

    assert ls.steps == {}

    ls.root_path = GRIZZLY_PROJECT

    with caplog.at_level(logging.INFO, 'grizzly_ls.server'):
        compile_inventory(ls)

    assert len(caplog.messages) == 1

    assert not ls.steps == {}
    assert len(ls.normalizer.custom_types.keys()) >= 8

    keywords = list(ls.steps.keys())

    for keyword in ['given', 'then', 'when']:
        assert keyword in keywords

    # Test file ignore pattern, default
    ls.steps.clear()
    caplog.clear()
    load_step_registry_mock = mocker.patch(
        'grizzly_ls.server.inventory.load_step_registry'
    )

    assert ls.steps == {}

    ls.root_path = GRIZZLY_PROJECT

    with caplog.at_level(logging.INFO, 'grizzly_ls.server'):
        compile_inventory(ls)

    assert len(caplog.messages) == 1

    assert load_step_registry_mock.call_count == 2
    mock_args = [
        arg[0][0][0].as_posix() for arg in load_step_registry_mock.call_args_list
    ]
    assert any(arg.endswith('/tests/project') for arg in mock_args)
    assert any(arg.endswith('/tests/project/steps') for arg in mock_args)

    # Test file ignore pattern, ignore below steps/
    ls.steps.clear()
    caplog.clear()
    ls.file_ignore_patterns = ['**/steps/*']
    load_step_registry_mock.reset_mock()

    assert ls.steps == {}

    ls.root_path = GRIZZLY_PROJECT

    with caplog.at_level(logging.INFO, 'grizzly_ls.server'):
        compile_inventory(ls)

    assert load_step_registry_mock.call_count == 1
    mock_args = [
        arg[0][0][0].as_posix() for arg in load_step_registry_mock.call_args_list
    ]
    assert any(arg.endswith('/tests/project') for arg in mock_args)

    # Test file ignore pattern, ignore below project/
    ls.steps.clear()
    caplog.clear()
    ls.file_ignore_patterns = ['**/project/*']
    load_step_registry_mock.reset_mock()

    assert ls.steps == {}

    ls.root_path = GRIZZLY_PROJECT

    with caplog.at_level(logging.INFO, 'grizzly_ls.server'):
        compile_inventory(ls)

    assert load_step_registry_mock.call_count == 1
    mock_args = [
        arg[0][0][0].as_posix() for arg in load_step_registry_mock.call_args_list
    ]
    assert any(arg.endswith('/tests/project/steps') for arg in mock_args)


def test_compile_keyword_inventory(lsp_fixture: LspFixture) -> None:
    ls = lsp_fixture.server

    ls.steps.clear()

    assert ls.steps == {}

    # create pre-requisites
    ls.root_path = GRIZZLY_PROJECT

    # indirect call to `compile_keyword_inventory`
    compile_inventory(ls)

    assert 'Feature' not in ls.keywords  # already used once in feature file
    assert 'Background' not in ls.keywords  # - " -
    assert 'And' in ls.keywords  # just an alias for Given, but we need want it
    assert 'Scenario' in ls.keywords  # can be used multiple times
    assert 'Given' in ls.keywords  # - " -
    assert 'When' in ls.keywords
