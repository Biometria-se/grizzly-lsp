import inspect
import logging
import platform
import warnings
import signal
import re

from os import environ
from os.path import pathsep
from typing import Any, Tuple, Dict, List, Union, Optional, Callable
from types import FrameType
from pathlib import Path
from behave.matchers import ParseMatcher
from pip._internal.cli.main import main as pipmain
from venv import create as venv_create
from tempfile import gettempdir
from difflib import get_close_matches, SequenceMatcher
from urllib.parse import urlparse, unquote
from importlib import import_module

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

from behave.step_registry import registry
from behave.runner_util import load_step_modules
from behave.i18n import languages

from .text import Coordinate, NormalizeHolder, RegexPermutationResolver, Normalizer



class GrizzlyLanguageServer(LanguageServer):
    logger: logging.Logger = logging.getLogger(__name__)

    steps: Dict[str, List[str]]
    keywords: List[str]
    keywords_once: List[str] = ['Feature', 'Background']
    keyword_alias: Dict[str, str] = {
        'But': 'Then',
        'And': 'Given',
    }

    normalizer: Normalizer

    def show_message(self, message: str, msg_type: Optional[MessageType] = MessageType.Info) -> None:
        super().show_message(message, msg_type=msg_type)  # type: ignore

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
                self.show_message(f'creating virtual environment for language server, this could take a while')
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
            self.show_message(message)

            self._make_keyword_registry()
            message = f'found {len(self.keywords)} keywords in behave'
            self.logger.debug(message)
            self.show_message(message)
            
        @self.feature(COMPLETION)
        def completion(params: CompletionParams) -> CompletionList:
            assert self.steps is not None, 'no steps in inventory'

            line = self._current_line(params.text_document.uri, params.position)

            line = re.sub(r'"[^"]"', '""', line)

            self.logger.debug(f'{line=}')

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
                            tags=None,
                            detail=None,
                            documentation=None,
                            deprecated=False,
                            preselect=None,
                            sort_text=None,
                            filter_text=None,
                            insert_text=None,
                            insert_text_format=None,
                            insert_text_mode=None,
                            text_edit=None,
                            additional_text_edits=None,
                            commit_characters=None,
                            command=None,
                            data=None,
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
                    matched_steps = get_close_matches(step, steps, len(steps), 0.2)
                    self.logger.debug(f'{step=}')
                    for matched_step in matched_steps:
                        score = SequenceMatcher(None, step, matched_step).ratio()
                        self.logger.debug(f'\t{matched_step=} {score=}')

                items = list(
                    map(
                        lambda s: CompletionItem(
                            label=s,
                            kind=CompletionItemKind.Function,
                            tags=None,
                            detail=None,
                            documentation=None,
                            deprecated=False,
                            preselect=None,
                            sort_text=None,
                            filter_text=None,
                            insert_text=None,
                            insert_text_format=None,
                            insert_text_mode=None,
                            text_edit=None,
                            additional_text_edits=None,
                            commit_characters=None,
                            command=None,
                            data=None,
                        ),
                        matched_steps,
                    )
                )

            return CompletionList(
                is_incomplete=False,
                items=items,
            )

    def _normalize_step_expression(self, step: Union[ParseMatcher, str]) -> List[str]:
        if isinstance(step, ParseMatcher):
            pattern = step.pattern
        else:
            pattern = step

        patterns, errors = self.normalizer(pattern)

        if len(errors) > 0:
            for message in errors:
                self.show_message(message, msg_type=MessageType.Error)
                self.logger.error(message)

        return patterns

    def _resolve_custom_types(self) -> None:
        custom_types: Dict[str, Callable[[str], Any]] = ParseMatcher.custom_types
        custom_type_permutations: Dict[str, NormalizeHolder] = {}

        for custom_type, func in custom_types.items():
            try:
                func_code = [line for line in inspect.getsource(func).strip().split('\n') if not line.strip().startswith('@classmethod')]
                message: Optional[str] = None

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

                        custom_type_permutations.update({
                            custom_type: NormalizeHolder(
                                permutations=coordinates,
                                replacements=RegexPermutationResolver.resolve(pattern),
                            ),
                        })
                    else:
                        raise ValueError(f'could not extract pattern from "{func_code[0]}" for custom type {custom_type}')
                elif 'from_string(' in func_code[-1] or 'from_string(' in func_code[0]:
                    enum_name: str

                    match = re.match(r'return ([^\.]*)\.from_string\(', func_code[-1].strip())
                    if match:
                        enum_name = match.group(1)
                        module = import_module('grizzly.types')
                    else:
                        match = re.match(r'def from_string.*?->\s+\'?([^:\']*)\'?:', func_code[0].strip())
                        if match:
                            enum_name = match.group(1)
                            module = inspect.getmodule(func)
                        else:
                            raise ValueError(f'could not find a from_string method for custom type {custom_type}')

                    enum_class = getattr(module, enum_name)
                    replacements = [value.name.lower() for value in enum_class]
                    vector = enum_class.get_vector()

                    if vector is None:
                        coordinates = Coordinate()
                    else:
                        x, y = vector
                        coordinates = Coordinate(x=x, y=y)

                    custom_type_permutations.update({
                        custom_type: NormalizeHolder(
                            permutations=coordinates,
                            replacements=replacements,
                        ),
                    })
                else:
                    raise ValueError(f'cannot infere what {func} will return for {custom_type}')
            except ValueError as e: 
                message = str(e)
                self.logger.error(message)
                self.show_message(message, msg_type=MessageType.Error) 

        self.normalizer = Normalizer(custom_type_permutations)

    def _make_step_registry(self, step_path: Path) -> None:
        self.logger.debug(f'loading step modules from {step_path}...')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            load_step_modules([str(step_path)])
            self.logger.info(f'{ParseMatcher.custom_types=}')

        self.logger.debug(f'...done!')
        self._resolve_custom_types()
        self.steps = {}
        registry_steps: Dict[str, List[ParseMatcher]] = registry.steps

        for keyword, steps in registry_steps.items():
            normalized_steps: List[str] = []
            for step in steps:
                normalized_steps += self._normalize_step_expression(step)

            self.steps.update({keyword: normalized_steps})

        self.logger.debug(self.steps)

    def _make_keyword_registry(self) -> None:
        self.keywords = ['Scenario'] + list(self.keyword_alias.keys())

        language_en = languages.get('en', {})
        for keyword in self.steps.keys():
            for value in language_en.get(keyword, []):
                if value in [u'*']:
                    continue

                self.keywords.append(value.strip())

    def _current_line(self, uri: str, position: Position) -> str:
        document = self.workspace.get_document(uri)
        content = document.source
        line = content.split('\n')[position.line]

        return line
