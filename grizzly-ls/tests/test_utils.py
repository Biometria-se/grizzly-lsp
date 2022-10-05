import parse

from enum import Enum

import pytest

from pytest_mock import MockerFixture

from grizzly_ls.utils import create_step_normalizer
from grizzly_extras.text import permutation, PermutationEnum
from grizzly.types import MessageDirection


@parse.with_pattern(r'(hello|world|foo|bar)')
@permutation(
    vector=(
        False,
        True,
    )
)
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


def test_create_normalizer(mocker: MockerFixture) -> None:
    mocker.patch('grizzly_ls.utils.ParseMatcher.custom_types', {})

    normalizer = create_step_normalizer()
    assert normalizer.custom_types == {}

    mocker.patch(
        'grizzly_ls.utils.ParseMatcher.custom_types',
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
        'grizzly_ls.utils.ParseMatcher.custom_types',
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
        'grizzly_ls.utils.ParseMatcher.custom_types',
        {
            'EnumError': DummyEnumNoFromString.magic,
        },
    )

    with pytest.raises(ValueError) as ve:
        create_step_normalizer()
    assert (
        str(ve.value)
        == 'cannot infere what <bound method DummyEnumNoFromString.magic of <enum \'DummyEnumNoFromString\'>> will return for EnumError'
    )

    mocker.patch(
        'grizzly_ls.utils.ParseMatcher.custom_types',
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
