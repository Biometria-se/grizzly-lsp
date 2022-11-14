import re
import itertools
import string
import inspect
import sys

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
)
from dataclasses import dataclass, field
from sre_constants import (  # pylint: disable=no-name-in-module  # type: ignore
    _NamedIntConstant as SreNamedIntConstant,  # type: ignore
    ANY,
    BRANCH,
    LITERAL,
    MAX_REPEAT,
    SUBPATTERN,
)
from sre_parse import SubPattern, parse as sre_parse

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
SreParseValue = Union[
    int, SreNamedIntConstant, SreParseValueMaxRepeat, SreParseValueBranch
]


class regexp_handler:
    sre_type: SreNamedIntConstant

    def __init__(self, sre_type: SreNamedIntConstant) -> None:
        self.sre_type = sre_type

    def __call__(
        self, func: Callable[['RegexPermutationResolver', SreParseValue], List[str]]
    ) -> Callable[['RegexPermutationResolver', SreParseValue], List[str]]:
        setattr(func, '__handler_type__', self.sre_type)

        return func

    @classmethod
    def make_registry(
        cls, instance: 'RegexPermutationResolver'
    ) -> Dict[SreNamedIntConstant, Callable[[SreParseValue], List[str]]]:
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
    def handle_any(self, _: SreParseValue) -> List[str]:
        printables: List[str] = []
        printables[:0] = string.printable

        return printables

    @regexp_handler(BRANCH)
    def handle_branch(self, token_value: SreParseValue) -> List[str]:
        token_value = cast(SreParseValueBranch, token_value)
        _, value = token_value
        options: Set[str] = set()

        for tokens in value:
            option = self.permute_tokens(tokens)
            options.update(option)

        return list(options)

    @regexp_handler(LITERAL)
    def handle_literal(self, value: SreParseValue) -> List[str]:
        value = cast(int, value)

        return [chr(value)]

    @regexp_handler(MAX_REPEAT)
    def handle_max_repeat(self, value: SreParseValue) -> List[str]:
        minimum, maximum, subpattern = cast(SreParseValueMaxRepeat, value)

        if maximum > 5000:
            raise ValueError(f'too many repetitions requested ({maximum}>5000)')

        values: List[Generator[List[str], None, None]] = []

        for sub_token, sub_value in subpattern:  # type: ignore
            options = self.handle_token(sub_token, sub_value)

            for x in range(minimum, maximum + 1):
                joined = self.cartesian_join([options] * x)
                values.append(joined)

        return [''.join(it) for it in itertools.chain(*values)]

    @regexp_handler(SUBPATTERN)
    def handle_subpattern(self, value: SreParseValue) -> List[str]:
        tokens = cast(SreParseValueSubpattern, value)[-1]
        return list(self.permute_tokens(tokens))

    def handle_token(
        self, token: SreNamedIntConstant, value: SreParseValue
    ) -> List[str]:
        try:
            return self._handlers[token](value)
        except KeyError:
            raise ValueError(f'unsupported regular expression construct {token}')

    def permute_tokens(self, tokens: SreParseTokens) -> List[str]:
        lists: List[List[str]]
        lists = [
            self.handle_token(token, cast(SreParseValue, value))
            for token, value in tokens  # type: ignore
        ]
        output: List[str] = []
        for list in self.cartesian_join(lists):
            output.append(''.join(list))

        return output

    def cartesian_join(
        self, input: List[List[str]]
    ) -> Generator[List[str], None, None]:
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
    custom_types: Dict[str, NormalizeHolder]

    def __init__(self, custom_types: Dict[str, NormalizeHolder]) -> None:
        self.custom_types = custom_types

    def __call__(self, pattern: str) -> Tuple[List[str], List[str]]:
        patterns: List[str] = []
        errors: Set[str] = set()

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
                    # @TODO: remove after new version of grizzly has been released
                    if variable_type == 'ContentType':
                        holder.permutations.y = True
                    normalize.update({variable: holder})
                elif len(variable_type) == 1:  # native types
                    normalize.update(
                        {
                            variable: NormalizeHolder(
                                permutations=Coordinate(), replacements=['']
                            )
                        }
                    )
                else:
                    errors.add(f'unhandled type: {variable=}, {variable_type=}')

            # replace variables that does not create any variations
            normalize_no_variations = {
                key: value
                for key, value in normalize.items()
                if not value.permutations.x and not value.permutations.y
            }
            if len(normalize_no_variations) > 0:
                for variable, holder in normalize_no_variations.items():
                    for replacement in holder.replacements:
                        pattern = pattern.replace(variable, replacement)

            # round 1, to create possible prenumtations
            normalize_variations_y = {
                key: value for key, value in normalize.items() if value.permutations.y
            }
            variation_patterns: Set[str]

            if len(normalize_variations_y) > 0:
                variation_patterns = set()
                for variable, holder in normalize_variations_y.items():
                    for replacement in holder.replacements:
                        variation_patterns.add(pattern.replace(variable, replacement))

                patterns = list(variation_patterns)

            normalize_variations_x = {
                key: value for key, value in normalize.items() if value.permutations.x
            }
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
            normalize_variations_y = {
                key: value for key, value in normalize.items() if value.permutations.y
            }
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
                                normalized_pattern = pattern.replace(
                                    variable, replacement
                                )
                                variation_patterns.add(normalized_pattern)
                                # are there any remaining replacements that should be resolved?
                                if (
                                    '{' in normalized_pattern
                                    and '}' in normalized_pattern
                                ):
                                    repeat_round_2 = True

                    if len(variation_patterns) > 0:
                        patterns = list(variation_patterns)

        # no variables in step, just add it
        if not has_matches and not has_typed_matches or len(patterns) < 1:
            patterns.append(pattern)

        return patterns, list(errors)


def get_step_parts(line: str) -> Tuple[Optional[str], Optional[str]]:
    if len(line) > 0:
        # remove any user values enclosed with double-quotes
        line = re.sub(r'"[^"]*"', '""', line)

        # remove multiple white spaces
        line = re.sub(r'^\s+', '', line)
        line = re.sub(r'\s{2,}', ' ', line)
        if sys.platform == 'win32':
            line = line.replace('\r', '')

        try:
            keyword, step = line.split(' ', 1)
            step = step
        except ValueError:
            keyword = line
            step = None
        keyword = keyword.strip()
    else:
        keyword, step = None, None

    return keyword, step


def clean_help(text: str) -> str:
    matches = re.finditer(r'\{@pylink ([^\}]*)}', text, re.MULTILINE)

    # @TODO: can we reverse engineer the URL based on the text?
    for match in matches:
        _, replacement_text = match.group(1).rsplit('.', 1)
        text = text.replace(match.group(), replacement_text)

    return '\n'.join([line.lstrip() for line in text.split('\n')])
