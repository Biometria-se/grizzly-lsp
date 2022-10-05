import warnings
import inspect
import re

from typing import Dict, List, Optional
from types import ModuleType
from importlib import import_module
from pathlib import Path
from behave.matchers import ParseMatcher

from behave.step_registry import registry
from behave.runner_util import load_step_modules as behave_load_step_modules

from .text import Normalizer, NormalizeHolder, Coordinate, RegexPermutationResolver


def load_step_registry(step_path: Path) -> Dict[str, List[ParseMatcher]]:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        behave_load_step_modules([str(step_path)])

    return registry.steps


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
        else:
            raise ValueError(f'cannot infere what {func} will return for {custom_type}')

    return Normalizer(custom_type_permutations)
