import warnings
import inspect
import re
import os
import subprocess
import logging

from typing import Dict, List, Optional, Tuple
from types import ModuleType
from importlib import import_module
from pathlib import Path

from behave.matchers import ParseMatcher
from behave.step_registry import registry
from behave.runner_util import load_step_modules as behave_load_step_modules

from .text import Normalizer, NormalizeHolder, Coordinate, RegexPermutationResolver


logger = logging.getLogger(__name__)


def load_step_registry(step_paths: List[Path]) -> Dict[str, List[ParseMatcher]]:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        behave_load_step_modules([str(step_path) for step_path in step_paths])

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

    return Normalizer(custom_type_permutations)


def run_command(
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> Tuple[int, List[str]]:
    output: List[str] = []

    if env is None:
        env = os.environ.copy()

    if cwd is None:
        cwd = os.getcwd()

    process = subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:
                break

            buffer = stdout.readline()
            if not buffer:
                break

            output.append(buffer.decode('utf-8'))

        process.terminate()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            process.kill()
        except Exception:
            pass

    process.wait()

    return process.returncode, output
