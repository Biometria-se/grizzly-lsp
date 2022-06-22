from dataclasses import dataclass, field
import logging
import platform
import warnings
import signal
import re

from os import environ
from os.path import pathsep
from typing import Any, Tuple, Dict, List
from types import FrameType
from pathlib import Path
from behave.matchers import ParseMatcher
from pip._internal.cli.main import main as pipmain
from venv import create as venv_create
from tempfile import gettempdir
from difflib import get_close_matches
from urllib.parse import urlparse, unquote

import gevent.monkey  # type: ignore

from pygls.server import LanguageServer
from pygls.lsp.methods import (
    COMPLETION,
    INITIALIZE,
)
from pygls.lsp.types import (
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind,
    InitializeParams,
    MessageType,
)
from pygls.lsp.types.basic_structures import Position

from behave.runner_util import load_step_modules
from behave.step_registry import registry
from behave.i18n import languages


class GrizzlyLanguageServer(LanguageServer):
    logger: logging.Logger = logging.getLogger(__name__)

    steps: Dict[str, List[str]]
    keywords: List[str]
    keywords_once: List[str] = ['Feature', 'Background']
    keyword_alias: Dict[str, str] = {
        'But': 'Then',
        'And': 'Given',
    }

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)  # type: ignore

        self.steps = {}
        self.keywords = []

        # monkey patch functions to short-circuit them (causes problems in this context)
        gevent.monkey.patch_all = lambda: None

        def _signal(signum: int, frame: FrameType) -> None:
            return

        signal.signal = _signal

        @self.feature(INITIALIZE)
        def initialize(params: InitializeParams) -> None:
            assert params.root_path is not None or params.root_uri is not None, f'neither root_path or root_uri was received from client'

            root_path = Path(params.root_path) if params.root_path is not None else Path(unquote(urlparse(params.root_uri).path)) if params.root_uri is not None else None

            assert root_path is not None

            project_name = root_path.stem

            virtual_environment = Path(gettempdir()) / f'grizzly-ls-{project_name}'

            self.logger.debug(f'looking for venv at {virtual_environment}')

            has_venv = virtual_environment.exists()

            if not has_venv:
                self.logger.debug(f'creating virtual environment: {virtual_environment}')
                venv_create(str(virtual_environment))

            if platform.system() == 'Windows':  # pragma: no cover
                bin_dir = 'Scripts'
            else:
                bin_dir = 'bin'

            paths = [str(virtual_environment / bin_dir), environ.get('PATH', '')]
            self.logger.debug('updating environment variables for venv')
            environ.update(
                {
                    'PATH': pathsep.join(paths),
                    'VIRTUAL_ENV': str(virtual_environment),
                    'PYTHONPATH': str(root_path / 'features'),
                }
            )

            if not has_venv:
                requirements_file = root_path / 'requirements.txt'
                self.logger.debug(f'installing {requirements_file}')
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    pipmain(['install', '-r', str(requirements_file)])

            self.logger.debug('creating step registry')
            self._make_step_registry(root_path / 'features' / 'steps')
            total_steps = 0
            for steps in self.steps.values():
                total_steps += len(steps)
            message = f'found {total_steps} steps in grizzly project {project_name}'
            self.logger.debug(message)
            self.show_message(message)  # type: ignore

            self._make_keyword_registry()
            message = f'found {len(self.keywords)} keywords in behave'
            self.logger.debug(message)
            self.show_message(message)  # type: ignore
            
        @self.feature(COMPLETION)
        def completion(params: CompletionParams) -> CompletionList:
            assert self.steps is not None, 'no steps in inventory'

            line = self._current_line(params.text_document.uri, params.position)

            if len(line.strip()) > 0:
                try:
                    keyword, step = line.strip().split(' ', 1)
                except ValueError:
                    keyword = line
                    step = None
                keyword = keyword.strip()
            else:
                keyword, step = None, None

            items: List[CompletionItem] = []

            document = self.workspace.get_document(params.text_document.uri)

            self.logger.debug(f'{keyword=}, {step=}, {self.keywords=}')

            if keyword is not None:
                keyword = self.keyword_alias.get(keyword, keyword)

            if keyword is None or keyword not in self.keywords:
                keywords = self.keywords.copy()
                for keyword_once in self.keywords_once:
                    if f'{keyword_once}:' not in document.source:
                        keywords.append(keyword_once)

                # check for partial matches
                if keyword is not None:
                    keywords = list(filter(lambda k: keyword.lower() in k.lower(), keywords))

                items = list(
                    map(
                        lambda k: CompletionItem(
                            label=k,
                            kind=CompletionItemKind.Keyword,
                        ),
                        sorted(keywords),
                    )
                )
            elif keyword is not None:
                steps = self.steps.get(keyword.lower(), [])

                matched_steps: List[str]

                if step is None:
                    matched_steps = steps
                else:
                    matched_steps = get_close_matches(step, steps, len(steps), 0)
                    self.logger.debug(f'{matched_steps=}')

                items = list(map(lambda s: CompletionItem(label=s, kind=CompletionItemKind.Function), matched_steps))

            return CompletionList(
                is_incomplete=False,
                items=items,
            )

    def _get_step_expressions(self, step: ParseMatcher) -> List[str]:
        pattern = step.pattern
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

        @dataclass
        class Replacement:
            variations: bool = field(default=False)
            replacements: List[str] = field(default_factory=list)

        has_typed_matches = re.search(typed_regex, pattern)
        if has_typed_matches:
            typed_matches = re.finditer(typed_regex, pattern)
            replacement_map: Dict[str, Replacement] = {}
            for match in typed_matches:
                variable = match.group(0)
                variable_type = match.group(1)

                if len(variable_type) == 1:  # native types
                    replacement_map.update({variable: Replacement(variations=False, replacements=[''])})
                elif variable_type == 'UserGramaticalNumber':
                    replacement_map.update({variable: Replacement(variations=False, replacements=['user', 'users'])})
                elif variable_type == 'MessageDirection':
                    replacement_map.update({variable: Replacement(variations=True, replacements=['client', 'server'])})
                elif variable_type == 'IterationGramaticalNumber':
                    replacement_map.update({variable: Replacement(variations=False, replacements=['iteration', 'iterations'])})
                elif variable_type == 'Direction':
                    replacement_map.update({variable: Replacement(variations=True, replacements=['to', 'from'])})
                elif variable_type == 'ResponseTarget':
                    replacement_map.update({variable: Replacement(variations=False, replacements=['metadata', 'payload'])})
                elif variable_type == 'Condition':
                    replacement_map.update({variable: Replacement(variations=False, replacements=['is', 'is not'])})
                elif variable_type in ['ContentType', 'TransformerContentType']:
                    replacement_map.update({variable: Replacement(variations=False, replacements=[''])})
                elif variable_type == 'Method':
                    replacement_map.update({variable: Replacement(variations=False, replacements=['send', 'post', 'put', 'receive', 'get'])})
                else:
                    message = f'unhandled type: {variable=}, {variable_type=}'
                    self.show_message(message, msg_type=MessageType.Error)  # type: ignore
                    self.logger.error(message)

            for variable, rule in replacement_map.items():
                for replacement in rule.replacements:
                    args = (variable, replacement,)
                    if rule.variations:
                        args += (1, )

                    pattern = pattern.replace(*args)  # type: ignore

            patterns.append(pattern) 

        # no variables in step, just add it
        if not has_matches and not has_typed_matches:
            patterns.append(pattern)
        elif len(patterns) > 0:
            print(patterns)

        return patterns

    def _make_step_registry(self, step_path: Path) -> None:
        self.logger.debug(f'loading step modules from {step_path}...')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            
            load_step_modules([str(step_path)])
        self.logger.debug(f'...done!')

        self.steps = {}
        registry_steps: Dict[str, List[ParseMatcher]] = registry.steps

        for keyword, steps in registry_steps.items():
            normalized_steps: List[str] = []
            for step in steps:
                normalized_steps += self._get_step_expressions(step)

            self.steps.update({keyword: normalized_steps})

            for keyword, steps in self.steps.items():
                print(f'{keyword=}')
                for step in steps:
                    print('\t' + step)

        self.logger.debug(self.steps)

    def _make_keyword_registry(self) -> None:
        self.keywords = ['Scenario'] + list(self.keyword_alias.keys())

        language_en = languages.get('en', {})
        for keyword in self.steps.keys():
            for value in language_en.get(keyword, []):
                if value in [u'*']:
                    continue

                self.keywords.append(value)

    def _current_line(self, uri: str, position: Position) -> str:
        document = self.workspace.get_document(uri)
        content = document.source
        line = content.split('\n')[position.line]

        return line
