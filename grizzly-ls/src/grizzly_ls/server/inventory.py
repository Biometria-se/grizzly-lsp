from __future__ import annotations

import logging
import warnings
import inspect
import re

from typing import List, Dict, Optional, TYPE_CHECKING
from types import ModuleType
from importlib import import_module
from pathlib import Path

from lsprotocol.types import MessageType
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


logger = logging.getLogger(__name__)


def load_step_registry(step_paths: List[Path]) -> Dict[str, List[ParseMatcher]]:
    from behave import step_registry

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        behave_load_step_modules([str(step_path) for step_path in step_paths])

    return step_registry.registry.steps.copy()


def create_step_normalizer() -> Normalizer:
    custom_type_permutations: Dict[str, NormalizeHolder] = {}

    for custom_type, func in ParseMatcher.custom_types.items():
        func_code = [
            line
            for line in inspect.getsource(func).strip().split('\n')
            if not line.strip().startswith('@classmethod')
        ]

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
                raise ValueError(
                    f'could not extract pattern from "{func_code[0]}" for custom type {custom_type}'
                )
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
                    raise ValueError(
                        f'could not find the type that from_string method for custom type {custom_type} returns'
                    )

            enum_class = getattr(module, enum_name)
            replacements = [value.name.lower() for value in enum_class]
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

    return Normalizer(custom_type_permutations)


def compile_inventory(ls: GrizzlyLanguageServer, silent: bool = False) -> None:
    logger.debug('creating step registry')
    project_name = ls.root_path.stem

    try:
        ls.behave_steps.clear()
        ls.behave_steps = load_step_registry(
            [path.parent for path in ls.root_path.rglob('*.py')]
        )
    except Exception as e:
        ls.show_message(
            f'unable to load behave step expressions:\n{str(e)}',
            msg_type=MessageType.Error,
        )
        return

    try:
        ls.normalizer = create_step_normalizer()
    except ValueError as e:
        ls.show_message(str(e), msg_type=MessageType.Error)
        return

    compile_step_inventory(ls)

    total_steps = 0
    for steps in ls.steps.values():
        total_steps += len(steps)

    compile_keyword_inventory(ls)

    message = (
        f'found {len(ls.keywords)} keywords and {total_steps} steps in "{project_name}"'
    )
    if not silent:
        ls.show_message(message)
    else:
        ls.logger.info(message)


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
    for key, values in ls.localizations.items():
        if values[0] != u'*':
            ls.keywords_headers.extend([*ls.localizations.get(key, [])])

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
