# pyright: reportGeneralTypeIssues=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false
from __future__ import annotations

import re
import itertools
import string
import inspect
import sys
import unicodedata
import tokenize

from contextlib import suppress
from typing import (
    List,
    Optional,
    Dict,
    Set,
    Tuple,
    Union,
    Generator,
    Any,
    Callable,
    cast,
    TYPE_CHECKING,
)
from dataclasses import dataclass, field
from tokenize import TokenInfo

from lsprotocol.types import Position
from pygls.workspace import TextDocument

from grizzly_ls.constants import MARKER_LANGUAGE


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


if sys.version_info >= (3, 11):
    from re._constants import _NamedIntConstant as SreNamedIntConstant  # type: ignore [reportMissingStubs]
    from re._constants import ANY, BRANCH, LITERAL, MAX_REPEAT, SUBPATTERN  # type: ignore [reportAttributeAccessIssue]

    from re._parser import parse as sre_parse, SubPattern  # type: ignore
else:  # pragma: no cover
    from sre_constants import (
        _NamedIntConstant as SreNamedIntConstant,
        ANY,
        BRANCH,
        LITERAL,
        MAX_REPEAT,
        SUBPATTERN,
    )
    from sre_parse import SubPattern, parse as sre_parse  # type: ignore

SreParseTokens = Union[
    List[
        Tuple[
            SreNamedIntConstant,
            Union[int, Tuple[int, int, List[Tuple[SreNamedIntConstant, int]]]],
        ]
    ],
    SubPattern,
]
SreParseValueBranch = Tuple[Optional[Any], List[SubPattern]]
SreParseValueMaxRepeat = Tuple[int, int, SubPattern]
SreParseValueSubpattern = Tuple[int, int, int, SreParseTokens]
SreParseValue = Union[int, SreNamedIntConstant, SreParseValueMaxRepeat, SreParseValueBranch]


class regexp_handler:
    sre_type: SreNamedIntConstant

    def __init__(self, sre_type: SreNamedIntConstant) -> None:
        self.sre_type = sre_type

    def __call__(
        self,
        func: Callable[[RegexPermutationResolver, SreParseValue], List[str]],
    ) -> Callable[[RegexPermutationResolver, SreParseValue], List[str]]:
        setattr(func, '__handler_type__', self.sre_type)

        return func

    @classmethod
    def make_registry(cls, instance: RegexPermutationResolver) -> Dict[SreNamedIntConstant, Callable[[SreParseValue], List[str]]]:
        registry: Dict[SreNamedIntConstant, Callable[[SreParseValue], List[str]]] = {}
        for name, func in inspect.getmembers(instance, predicate=inspect.ismethod):
            if name.startswith('_'):
                continue

            handler_type = getattr(func, '__handler_type__', None)

            if handler_type is None:
                continue

            registry.update({handler_type: func})

        return registry


class RegexPermutationResolver:
    """
    This code is more or less a typed and stripped down version of:
    https://gist.github.com/Quacky2200/714acad06f3f80f6bdb92d7d49dea4bf
    """

    _handlers: Dict[SreNamedIntConstant, Callable[[SreParseValue], List[str]]]

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self._handlers = regexp_handler.make_registry(self)

    @regexp_handler(ANY)
    def handle_any(self: RegexPermutationResolver, _: SreParseValue) -> List[str]:
        printables: List[str] = []
        printables[:0] = string.printable

        return printables

    @regexp_handler(BRANCH)
    def handle_branch(self: RegexPermutationResolver, token_value: SreParseValue) -> List[str]:
        token_value = cast(SreParseValueBranch, token_value)
        _, value = token_value
        options: Set[str] = set()

        for tokens in value:
            option = self.permute_tokens(tokens)
            options.update(option)

        return list(options)

    @regexp_handler(LITERAL)
    def handle_literal(self: RegexPermutationResolver, value: SreParseValue) -> List[str]:
        value = cast(int, value)

        return [chr(value)]

    @regexp_handler(MAX_REPEAT)
    def handle_max_repeat(self: RegexPermutationResolver, value: SreParseValue) -> List[str]:
        minimum, maximum, subpattern = cast(SreParseValueMaxRepeat, value)

        if maximum > 5000:
            raise ValueError(f'too many repetitions requested ({maximum}>5000)')

        values: List[Generator[List[str], None, None]] = []

        for sub_token, sub_value in subpattern:  # type: ignore
            options = self.handle_token(cast(SreNamedIntConstant, sub_token), cast(SreParseValue, sub_value))

            for x in range(minimum, maximum + 1):
                joined = self.cartesian_join([options] * x)
                values.append(joined)

        return [''.join(it) for it in itertools.chain(*values)]

    @regexp_handler(SUBPATTERN)
    def handle_subpattern(self: RegexPermutationResolver, value: SreParseValue) -> List[str]:
        tokens = cast(SreParseValueSubpattern, value)[-1]
        return list(self.permute_tokens(tokens))

    def handle_token(self, token: SreNamedIntConstant, value: SreParseValue) -> List[str]:
        try:
            return self._handlers[token](value)
        except KeyError:
            raise ValueError(f'unsupported regular expression construct {token}')

    def permute_tokens(self, tokens: SreParseTokens) -> List[str]:
        lists: List[List[str]]
        lists = [self.handle_token(token, cast(SreParseValue, value)) for token, value in tokens]  # type: ignore
        output: List[str] = []
        for list in self.cartesian_join(lists):
            output.append(''.join(list))

        return output

    def cartesian_join(self, input: List[List[str]]) -> Generator[List[str], None, None]:
        def rloop(
            sequence: List[List[str]],
            combinations: List[str],
        ) -> Generator[List[str], None, None]:
            if len(sequence) > 0:
                for _combination in sequence[0]:
                    _combinations = combinations + [_combination]
                    for item in rloop(sequence[1:], _combinations):
                        yield item
            else:
                yield combinations

        return rloop(input, [])

    def get_permutations(self) -> List[str]:
        tokens: SreParseTokens = [
            (
                token,
                value,
            )
            for token, value in sre_parse(self.pattern)  # type: ignore
        ]

        return self.permute_tokens(tokens)

    @staticmethod
    def resolve(pattern: str) -> List[str]:
        instance = RegexPermutationResolver(pattern)
        return instance.get_permutations()


@dataclass
class Coordinate:
    x: Optional[bool] = field(default=False)
    y: Optional[bool] = field(default=False)


@dataclass
class NormalizeHolder:
    permutations: Coordinate
    replacements: List[str]


class Normalizer:
    ls: GrizzlyLanguageServer
    custom_types: Dict[str, NormalizeHolder]

    def __init__(self, ls: GrizzlyLanguageServer, custom_types: Dict[str, NormalizeHolder]) -> None:
        self.ls = ls
        self.custom_types = custom_types

    def __call__(self, pattern: str) -> List[str]:
        patterns: List[str] = []

        # replace all non typed variables first, will only result in 1 step
        regex = r'\{[^\}:]*\}'
        has_matches = re.search(regex, pattern)
        if has_matches:
            matches = re.finditer(regex, pattern)
            for match in matches:
                pattern = pattern.replace(match.group(0), '')

        # replace all typed variables, can result in more than 1 step
        typed_regex = r'\{[^:]*:([^\}]*)\}'

        normalize: Dict[str, NormalizeHolder] = {}
        has_typed_matches = re.search(typed_regex, pattern)
        if has_typed_matches:
            typed_matches = re.finditer(typed_regex, pattern)
            for match in typed_matches:
                variable = match.group(0)
                variable_type = match.group(1)

                holder = self.custom_types.get(variable_type, None)
                if holder is not None:
                    normalize.update({variable: holder})
                elif len(variable_type) == 1:  # native types
                    normalize.update({variable: NormalizeHolder(permutations=Coordinate(), replacements=[''])})
                else:
                    with suppress(Exception):
                        start, end = match.span()

                        # if custom type is quoted (e.g. input variable), replace it with nothing
                        if pattern[start - 1] == pattern[end] == '"':
                            normalize.update({variable: NormalizeHolder(permutations=Coordinate(), replacements=[''])})

            # replace variables that does not create any variations
            normalize_no_variations = {key: value for key, value in normalize.items() if not value.permutations.x and not value.permutations.y}
            if len(normalize_no_variations) > 0:
                for variable, holder in normalize_no_variations.items():
                    for replacement in holder.replacements:
                        pattern = pattern.replace(variable, replacement)

            # round 1, to create possible prenumtations
            normalize_variations_y = {key: value for key, value in normalize.items() if value.permutations.y}
            variation_patterns: Set[str]

            if len(normalize_variations_y) > 0:
                variation_patterns = set()
                for variable, holder in normalize_variations_y.items():
                    for replacement in holder.replacements:
                        variation_patterns.add(pattern.replace(variable, replacement))

                patterns = list(variation_patterns)

            normalize_variations_x = {key: value for key, value in normalize.items() if value.permutations.x}
            if len(normalize_variations_x) > 0:
                matrix_components: List[List[str]] = []
                for holder in normalize_variations_x.values():
                    matrix_components.append(holder.replacements)

                # create unique combinations of all replacements
                matrix = list(
                    filter(
                        lambda p: p.count(p[0]) != len(p),
                        list(itertools.product(*matrix_components)),
                    )
                )

                variation_patterns = set()
                for pattern in patterns:
                    for row in matrix:
                        for variable in normalize_variations_x.keys():
                            if variable not in pattern:
                                continue

                            for replacement in row:
                                # all variables in pattern has been normalized
                                if variable not in pattern:
                                    break

                                # x replacements should only occur once in the pattern
                                if f' {replacement}' in pattern:
                                    continue

                                pattern = pattern.replace(variable, replacement)

                    variation_patterns.add(pattern)

                patterns = list(variation_patterns)

            # round 2, to normalize any additional unresolved prenumtations after normalizing x
            normalize_variations_y = {key: value for key, value in normalize.items() if value.permutations.y}
            if len(normalize_variations_y) > 0:
                repeat_round_2 = True

                # all remaining replacements needs to be resolved
                while repeat_round_2:
                    repeat_round_2 = False
                    variation_patterns = set()
                    for pattern in patterns:
                        for variable, holder in normalize_variations_y.items():
                            if variable not in pattern:
                                continue

                            for replacement in holder.replacements:
                                normalized_pattern = pattern.replace(variable, replacement)
                                variation_patterns.add(normalized_pattern)
                                # are there any remaining replacements that should be resolved?
                                if '{' in normalized_pattern and '}' in normalized_pattern:
                                    repeat_round_2 = True

                    if len(variation_patterns) > 0:
                        patterns = list(variation_patterns)

        # no variables in step, just add it
        if not has_matches and not has_typed_matches or len(patterns) < 1:
            patterns.append(pattern)

        return patterns


def get_step_parts(line: str) -> Tuple[Optional[str], Optional[str]]:
    if len(line) > 0:
        # remove multiple white spaces
        line = re.sub(r'^\s+', '', line)
        line = re.sub(r'\s{2,}', ' ', line)
        if sys.platform == 'win32':  # pragma: no cover
            line = line.replace('\r', '')

        try:
            keyword, step = line.split(' ', 1)
        except ValueError:
            keyword, step = line, None
        keyword = keyword.strip()
    else:
        keyword, step = None, None

    return keyword, step


def clean_help(text: str) -> str:
    matches = re.finditer(r'\{@pylink ([^\}]*)}', text, re.MULTILINE)

    for match in matches:
        _, replacement_text = match.group(1).rsplit('.', 1)
        text = text.replace(match.group(), replacement_text)

    return '\n'.join([line.lstrip() for line in text.split('\n')])


def get_tokens(text: str) -> List[TokenInfo]:
    """Own implementation of `tokenize.tokenize`, since it behaves differently between platforms
    and/or python versions.

    Any word/section in a string that is only alphanumerical characters is classified as NAME,
    everything else is OP.
    """
    tokens: List[TokenInfo] = []

    sections = text.strip().split(' ')
    end: int = 0

    indentation_end = len(text) - len(text.strip())

    if indentation_end > 0:
        text_indentation = text[0:indentation_end]
        tokens.append(TokenInfo(tokenize.INDENT, string=text_indentation, start=(1, 0), end=(1, indentation_end), line=text))

    for section in sections:
        # find where we are in the text
        start = text.index(section, end)
        end = start + len(section)

        if section.isalpha():
            tokens.append(
                TokenInfo(
                    tokenize.NAME,
                    string=section,
                    start=(1, start),
                    end=(1, end),
                    line=text,
                )
            )
        else:
            end -= len(section)  # wind back, since we need to start in the begining of the current section

            for char in section:
                tokens.append(TokenInfo(tokenize.OP, string=char, start=(1, start), end=(1, end), line=text))

                # move forward in the section
                start = text.index(char, end)
                end = start + len(char)

    return tokens


def format_arg_line(line: str) -> str:
    try:
        argument, description = line.split(':', 1)
        arg_name, arg_type = argument.split(' ')
        arg_type = arg_type.replace('(', '').replace(')', '').strip()

        return f'* {arg_name} `{arg_type}`: {description.strip()}'
    except ValueError:
        return f'* {line}'


def find_language(source: str) -> str:
    language: str = 'en'

    for line in source.splitlines():
        line = line.strip()
        if line.startswith(MARKER_LANGUAGE):
            try:
                _, lang = line.strip().split(': ', 1)
                lang = lang.strip()
                if len(lang) >= 2:
                    language = lang
            except ValueError:
                pass
            finally:
                break

    return language


def get_current_line(text_document: TextDocument, position: Position) -> str:
    source = text_document.source
    line = source.split('\n')[position.line]

    return line


def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text)

    return re.sub(r'[-\s]+', '-', text).strip('-_')


def remove_if_statements(content: str) -> str:
    buffer: List[str] = []
    lines = content.splitlines()
    remove_endif = False

    for line in lines:
        stripped_line = line.strip()

        if stripped_line[:2] == '{%' and stripped_line[-2:] == '%}':
            if '{$' in stripped_line and '$}' in stripped_line and 'if' in stripped_line:
                remove_endif = True
                continue

            if remove_endif and 'endif' in stripped_line:
                remove_endif = False
                continue

        buffer.append(line)

    return '\n'.join(buffer)
