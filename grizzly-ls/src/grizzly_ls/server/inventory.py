from __future__ import annotations

import warnings
import inspect
import re

from os import sep
from typing import Any, Iterable, List, Dict, Optional, TYPE_CHECKING, Set, cast
from types import ModuleType
from importlib import import_module
from pathlib import Path, PurePath

from behave.matchers import ParseMatcher
from behave.runner_util import load_step_modules as behave_load_step_modules
from behave.i18n import languages

from grizzly_ls.text import (
    Normalizer,
    NormalizeHolder,
    Coordinate,
    RegexPermutationResolver,
    clean_help,
)
from grizzly_ls.model import Step


if TYPE_CHECKING:
    from grizzly_ls.server import GrizzlyLanguageServer


def load_step_registry(step_paths: List[Path]) -> Dict[str, List[ParseMatcher]]:
    from behave import step_registry

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        behave_load_step_modules([str(step_path) for step_path in step_paths])

    return step_registry.registry.steps.copy()


def create_step_normalizer(ls: GrizzlyLanguageServer) -> Normalizer:
    custom_type_permutations: Dict[str, NormalizeHolder] = {}

    for custom_type, func in ParseMatcher.custom_types.items():
        func_code = [line for line in inspect.getsource(func).strip().split('\n') if not line.strip().startswith('@classmethod')]

        if func_code[0].startswith('@parse.with_pattern'):
            match = re.match(r'@parse.with_pattern\(r\'\(?(.*?)\)?\'', func_code[0])
            if match:
                pattern = match.group(1)
                vector = getattr(func, '__vector__', None)
                if vector is None:
                    coordinates = Coordinate()
                else:
                    x, y = vector
                    coordinates = Coordinate(x=x, y=y)

                custom_type_permutations.update(
                    {
                        custom_type: NormalizeHolder(
                            permutations=coordinates,
                            replacements=RegexPermutationResolver.resolve(pattern),
                        ),
                    }
                )
            else:
                raise ValueError(f'could not extract pattern from "{func_code[0]}" for custom type {custom_type}')
        elif 'from_string(' in func_code[-1] or 'from_string(' in func_code[0]:
            enum_name: str

            match = re.match(r'return ([^\.]*)\.from_string\(', func_code[-1].strip())
            module: Optional[ModuleType]
            if match:
                enum_name = match.group(1)
                module = import_module('grizzly.types')
            else:
                match = re.match(
                    r'def from_string.*?->\s+\'?([^:\']*)\'?:',
                    func_code[0].strip(),
                )
                if match:
                    enum_name = match.group(1)
                    module = inspect.getmodule(func)
                else:
                    raise ValueError(f'could not find the type that from_string method for custom type {custom_type} returns')

            enum_class = getattr(module, enum_name)

            def enum_value_getter(v: Any) -> str:
                try:
                    if not callable(getattr(v, 'get_value', None)):
                        raise NotImplementedError
                    enum_value = v.get_value()
                except NotImplementedError:
                    enum_value = v.name.lower()

                return cast(str, enum_value)

            replacements = [enum_value_getter(value) for value in enum_class]
            vector = enum_class.get_vector()

            if vector is None:
                coordinates = Coordinate()
            else:
                x, y = vector
                coordinates = Coordinate(x=x, y=y)

            custom_type_permutations.update(
                {
                    custom_type: NormalizeHolder(
                        permutations=coordinates,
                        replacements=replacements,
                    ),
                }
            )

    return Normalizer(ls, custom_type_permutations)


def _match_path(path: Path, pattern: str) -> bool:
    return any([PurePath(sep.join(path.parts[: i + 2])).match(pattern) for i in range(len(path.parts) - 1)])


def _filter_source_directories(file_ignore_patterns: List[str], source_file_paths: Iterable[Path]) -> Set[Path]:
    # Ignore [unix] hidden files, node_modules and bin by default
    if not file_ignore_patterns:
        file_ignore_patterns = [
            '**/.*',
            '**/node_modules',
            '**/bin',
        ]

    return set([path.parent for path in source_file_paths if path.parent.is_dir() and all(not _match_path(path.parent, ignore_pattern) for ignore_pattern in file_ignore_patterns)])


def compile_inventory(ls: GrizzlyLanguageServer, *, standalone: bool = False) -> None:
    ls.logger.debug('creating step registry')
    project_name = ls.root_path.stem

    try:
        ls.behave_steps.clear()
        paths = _filter_source_directories(ls.file_ignore_patterns, ls.root_path.rglob('*.py'))

        plain_paths = [path.as_posix() for path in paths]

        ls.logger.debug(f'loading steps from {plain_paths}')
        # ignore paths that contains errors
        for path in paths:
            try:
                ls.behave_steps.update(load_step_registry([path]))
            except Exception as e:
                ls.logger.exception(f'failed to load steps from {path}:\n{str(e)}')
    except Exception as e:
        if not standalone:
            ls.logger.exception(
                f'unable to load behave step expressions:\n{str(e)}',
                notify=True,
            )
            return

        raise e

    try:
        ls.normalizer = create_step_normalizer(ls)
    except ValueError as e:
        if not standalone:
            ls.logger.exception('unable to normalize step expression', notify=True)
            return

        raise e

    compile_step_inventory(ls)

    total_steps = 0
    for steps in ls.steps.values():
        total_steps += len(steps)

    compile_keyword_inventory(ls)

    ls.logger.info(f'found {len(ls.keywords)} keywords and {total_steps} steps in "{project_name}"')


def compile_step_inventory(ls: GrizzlyLanguageServer) -> None:
    for keyword, steps in ls.behave_steps.items():
        normalized_steps_all: List[Step] = []
        for step in steps:
            normalized_steps = ls._normalize_step_expression(step)
            steps_holder: List[Step] = []

            for normalized_step in normalized_steps:
                help = getattr(step.func, '__doc__', None)

                if help is not None:
                    help = clean_help(help)

                step_holder = Step(
                    keyword,
                    normalized_step,
                    func=step.func,
                    help=help,
                )
                steps_holder.append(step_holder)

            normalized_steps_all += steps_holder

        ls.steps.update({keyword: normalized_steps_all})


def compile_keyword_inventory(ls: GrizzlyLanguageServer) -> None:
    ls.localizations = languages.get(ls.language, {})
    if ls.localizations == {}:
        raise ValueError(f'unknown language "{ls.language}"')

    # localized any keywords
    ls.keywords_any = list(
        set(
            [
                '*',
                *ls.localizations.get('but', []),
                *ls.localizations.get('and', []),
            ]
        )
    )

    # localized keywords that should only appear once
    ls.keywords_once = list(
        set(
            [
                *ls.localizations.get('feature', []),
                *ls.localizations.get('background', []),
            ]
        )
    )

    ls.keywords_headers = []
    ls.keywords_all = []
    for key, values in ls.localizations.items():
        if values[0] != u'*':
            ls.keywords_headers.extend([*ls.localizations.get(key, [])])
            ls.keywords_all.extend([*values])
        else:
            ls.keywords_all.extend([*values[1:]])

    # localized keywords
    ls.keywords = list(
        set(
            [
                *ls.localizations.get('scenario', []),
                *ls.localizations.get('scenario_outline', []),
                *ls.localizations.get('examples', []),
                *ls.keywords_any,
            ]
        )
    )
    ls.keywords.remove('*')

    for keyword in ls.steps.keys():
        for value in ls.localizations.get(keyword, []):
            value = value.strip()
            if value in [u'*']:
                continue

            ls.keywords.append(value.strip())
