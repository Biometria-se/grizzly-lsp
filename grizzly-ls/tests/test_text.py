from typing import cast

import string

from sre_constants import (  # pylint: disable=no-name-in-module  # type: ignore
    _NamedIntConstant as SreNamedIntConstant,  # type: ignore
    ANY,
    BRANCH,
    LITERAL,
    MAX_REPEAT,
    SUBPATTERN,
    IN,
)

import pytest

from grizzly_ls.text import (
    RegexPermutationResolver,
    SreParseValue,
    SreParseValueMaxRepeat,
    get_step_parts,
)


class TestRegexPermutationResolver:
    def test__init__(self) -> None:
        resolver = RegexPermutationResolver('(hello|world)')

        assert list(sorted(resolver._handlers.keys())) == sorted(
            [
                ANY,
                BRANCH,
                LITERAL,
                MAX_REPEAT,
                SUBPATTERN,
            ]
        )
        assert resolver.pattern == '(hello|world)'

    def test_handle_any(self) -> None:
        resolver = RegexPermutationResolver('(hello|world)')

        assert ''.join(resolver.handle_any(1)) == string.printable
        assert ''.join(resolver.handle_any(1343)) == string.printable

    def test_handle_branch(self) -> None:
        resolver = RegexPermutationResolver('(hello|world)')

        assert sorted(
            resolver.handle_branch(
                cast(
                    SreParseValue,
                    (
                        None,
                        [
                            [
                                (
                                    LITERAL,
                                    104,
                                ),
                                (
                                    LITERAL,
                                    101,
                                ),
                                (
                                    LITERAL,
                                    108,
                                ),
                                (
                                    LITERAL,
                                    108,
                                ),
                                (
                                    LITERAL,
                                    111,
                                ),
                            ],
                            [
                                (
                                    LITERAL,
                                    119,
                                ),
                                (
                                    LITERAL,
                                    111,
                                ),
                                (
                                    LITERAL,
                                    114,
                                ),
                                (
                                    LITERAL,
                                    108,
                                ),
                                (
                                    LITERAL,
                                    100,
                                ),
                            ],
                        ],
                    ),
                )
            )
        ) == sorted(['hello', 'world'])

    def test_handle_literal(self) -> None:
        resolver = RegexPermutationResolver('(hello|world)')

        assert resolver.handle_literal(ord('A')) == ['A']
        assert resolver.handle_literal(ord('Å')) == ['Å']

    def test_handle_max_repeat(self) -> None:
        resolver = RegexPermutationResolver('(world[s]?)')

        with pytest.raises(ValueError) as ve:
            resolver.handle_max_repeat(
                cast(
                    SreParseValueMaxRepeat,
                    (
                        0,
                        5001,
                        [
                            (
                                LITERAL,
                                104,
                            ),
                            (
                                LITERAL,
                                105,
                            ),
                        ],
                    ),
                )
            )
        assert str(ve.value) == 'too many repetitions requested (5001>5000)'

        assert resolver.handle_max_repeat(
            cast(
                SreParseValueMaxRepeat,
                (
                    1,
                    2,
                    [
                        (
                            LITERAL,
                            104,
                        ),
                        (
                            LITERAL,
                            105,
                        ),
                    ],
                ),
            )
        ) == ['h', 'hh', 'i', 'ii']

    def test_handle_subpattern(self) -> None:
        resolver = RegexPermutationResolver('(world[s]?)')

        assert resolver.handle_subpattern(
            cast(
                SreParseValue,
                [
                    [
                        (
                            LITERAL,
                            119,
                        ),
                        (
                            LITERAL,
                            111,
                        ),
                    ],
                    [
                        (
                            LITERAL,
                            104,
                        ),
                        (
                            LITERAL,
                            105,
                        ),
                    ],
                ],
            )
        ) == ['hi']

    def test_handle_token(self) -> None:
        resolver = RegexPermutationResolver('(world[s]?)')

        test = SreNamedIntConstant(name='test', value=1337)

        with pytest.raises(ValueError) as ve:
            resolver.handle_token(test, 104)
        assert str(ve.value) == 'unsupported regular expression construct test'

        with pytest.raises(ValueError) as ve:
            resolver.handle_token(IN, 104)
        assert str(ve.value) == 'unsupported regular expression construct IN'

    def test_cartesian_join(self) -> None:
        resolver = RegexPermutationResolver('(world[s]?)')

        result = resolver.cartesian_join([['hello', 'world'], ['foo']])
        assert list(result) == [['hello', 'foo'], ['world', 'foo']]

        result = resolver.cartesian_join([['hello', 'world'], ['foo', 'bar']])
        assert list(result) == [
            ['hello', 'foo'],
            ['hello', 'bar'],
            ['world', 'foo'],
            ['world', 'bar'],
        ]

    def test_resolve(self) -> None:
        assert RegexPermutationResolver.resolve('(world[s]?)') == ['world', 'worlds']
        assert sorted(RegexPermutationResolver.resolve('(foo|bar)?')) == sorted(
            ['', 'foo', 'bar']
        )


def test_get_step_parts() -> None:
    assert get_step_parts('') == (
        None,
        None,
    )
    assert get_step_parts('   Giv') == (
        'Giv',
        None,
    )
    assert get_step_parts(' Given hello world') == (
        'Given',
        'hello world',
    )
    assert get_step_parts('  And are you "ok"?') == (
        'And',
        'are you ""?',
    )
    assert get_step_parts('     Then   make sure   that "value"  is "None"') == (
        'Then',
        'make sure that "" is ""',
    )
