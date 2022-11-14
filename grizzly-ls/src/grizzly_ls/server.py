import itertools
import logging
import platform
import signal
import subprocess
import sys
import re

from os import environ
from os.path import pathsep, sep
from typing import Any, Tuple, Dict, List, Union, Optional, Set, cast
from types import FrameType
from pathlib import Path
from behave.matchers import ParseMatcher
from venv import create as venv_create
from tempfile import gettempdir
from difflib import get_close_matches
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname
from time import perf_counter

import gevent.monkey  # type: ignore

from pygls.server import LanguageServer
from pygls.lsp.methods import (
    COMPLETION,
    INITIALIZE,
    WORKSPACE_DID_CHANGE_CONFIGURATION,
    HOVER,
    DEFINITION,
)
from pygls.lsp.types import (
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind,
    InitializeParams,
    DefinitionParams,
    MessageType,
    Hover,
    InsertTextFormat,
)
from pygls.lsp.types.workspace import (
    DidChangeConfigurationParams as WorkspaceDidChangeConfigurationParams,
)
from pygls.lsp.types.basic_structures import (
    Position,
    TextDocumentPositionParams,
    MarkupKind,
    MarkupContent,
    Range,
    LocationLink,
)
from pygls.workspace import Document

from behave.i18n import languages

from .text import Normalizer, get_step_parts, clean_help
from .utils import create_step_normalizer, load_step_registry
from . import __version__


class GrizzlyLanguageServer(LanguageServer):
    logger: logging.Logger = logging.getLogger(__name__)

    root_path: Path
    behave_steps: Dict[str, List[ParseMatcher]]
    steps: Dict[str, List[str]]
    help: Dict[str, str]
    keywords: List[str]
    keywords_once: List[str] = ['Feature', 'Background']
    keyword_any: List[str] = [
        'But',
        'And',
        '*',
    ]

    normalizer: Normalizer

    markup_kind: MarkupKind

    def show_message(
        self, message: str, msg_type: Optional[MessageType] = MessageType.Info
    ) -> None:
        super().show_message(message, msg_type=msg_type)  # type: ignore

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(name='grizzly-ls', version=__version__, *args, **kwargs)  # type: ignore

        self.behave_steps = {}
        self.steps = {}
        self.help = {}
        self.keywords = []
        self.markup_kind = MarkupKind.Markdown  # assume, until initiazed request

        # monkey patch functions to short-circuit them (causes problems in this context)
        gevent.monkey.patch_all = lambda: None

        def _signal(signum: Union[int, signal.Signals], frame: FrameType) -> None:
            return

        signal.signal = _signal  # type: ignore

        @self.feature(INITIALIZE)
        def initialize(params: InitializeParams) -> None:
            self.logger.debug(params)
            if params.root_path is None and params.root_uri is None:
                error_message = 'neither root_path or root uri was received from client'
                self.logger.error(error_message)
                self.show_message(error_message, msg_type=MessageType.Error)

            root_path = (
                Path(unquote(url2pathname(urlparse(params.root_uri).path)))
                if params.root_uri is not None
                else Path(cast(str, params.root_path))
            )

            # fugly as hell
            if (
                not root_path.exists()
                and str(root_path)[0:1] == sep
                and str(root_path)[2] == ':'
            ):
                root_path = Path(str(root_path)[1:])

            self.root_path = root_path

            self.logger.debug(f'workspace root: {root_path}')

            project_name = root_path.stem

            virtual_environment = Path(gettempdir()) / f'grizzly-ls-{project_name}'

            self.logger.debug(f'looking for venv at {virtual_environment}')

            has_venv = virtual_environment.exists()

            if not has_venv:
                self.logger.debug(
                    f'creating virtual environment: {virtual_environment}'
                )
                self.show_message(
                    'creating virtual environment for language server, this could take a while'
                )
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
                assert requirements_file.exists()
                self.logger.debug(f'installing {requirements_file}')
                start = perf_counter()
                try:
                    output = subprocess.check_output(
                        [
                            sys.executable,
                            '-m',
                            'pip',
                            'install',
                            '-r',
                            str(requirements_file),
                        ],
                        env=environ,
                    ).decode(sys.stdout.encoding)
                    self.logger.debug(output)
                    rc = 0
                except subprocess.CalledProcessError as e:
                    self.logger.error(e.output)
                    rc = e.returncode
                finally:
                    delta = (perf_counter() - start) * 1000
                    self.logger.debug(f'pip install took {delta} ms')

                if rc == 0:
                    self.show_message('virtual environment done')
                else:
                    self.show_message(
                        f'failed to install {requirements_file}',
                        msg_type=MessageType.Error,
                    )

            self._compile_inventory(root_path, project_name)

            markup_supported = self.client_capabilities.get_capability(
                'text_document.completion.completion_item.documentation_format',
                [MarkupKind.Markdown],
            )
            if len(markup_supported) < 1:
                self.markup_kind = MarkupKind.PlainText
            else:
                self.markup_kind = markup_supported[0]

        @self.feature(COMPLETION)
        def completion(params: CompletionParams) -> CompletionList:
            assert self.steps is not None, 'no steps in inventory'

            line = self._current_line(params.text_document.uri, params.position)
            keyword, step = get_step_parts(line)

            items: List[CompletionItem] = []
            document = self.workspace.get_document(params.text_document.uri)

            self.logger.debug(f'{keyword=}, {step=}, {self.keywords=}')

            if keyword is None or keyword not in self.keywords:
                items = self._complete_keyword(keyword, document)
            elif keyword is not None:
                items = self._complete_step(keyword, step)

            # self.logger.debug(f'completion: {items=}')

            return CompletionList(
                is_incomplete=False,
                items=items,
            )

        @self.feature(WORKSPACE_DID_CHANGE_CONFIGURATION)
        def workspace_did_change_configuration(
            params: WorkspaceDidChangeConfigurationParams,
        ) -> None:
            self.logger.debug(params)

        @self.feature(HOVER)
        def hover(params: TextDocumentPositionParams) -> Optional[Hover]:
            hover: Optional[Hover] = None
            help_text: Optional[str] = None
            current_line = self._current_line(params.text_document.uri, params.position)
            keyword, step = get_step_parts(current_line)

            self.logger.debug(f'{keyword=}, {step=}')

            if (
                step is None
                or keyword is None
                or (
                    keyword.lower() not in self.steps
                    and keyword not in self.keyword_any
                )
            ):
                return None

            start = current_line.index(keyword)
            end = len(current_line) - 1

            help_text = self._find_help(current_line)

            if help_text is None:
                return None

            if 'Args:' in help_text:
                pre, post = help_text.split('Args:', 1)
                text = '\n'.join(
                    [
                        self._format_arg_line(arg_line)
                        for arg_line in post.strip().split('\n')
                    ]
                )

                help_text = f'{pre}Args:\n\n{text}\n'

            contents = MarkupContent(kind=self.markup_kind, value=help_text)
            range = Range(
                start=Position(line=params.position.line, character=start),
                end=Position(line=params.position.line, character=end),
            )
            hover = Hover(contents=contents, range=range)

            return hover

        @self.feature(DEFINITION)
        def definition(params: DefinitionParams) -> Optional[List[LocationLink]]:
            current_line = self._current_line(params.text_document.uri, params.position)
            matches = re.finditer(r'"([^"]*)"', current_line, re.MULTILINE)
            definitions: List[LocationLink] = []

            for match in matches:
                variable_value = match.group(1)

                if variable_value.startswith('$conf::'):
                    # @TODO: preview with an environment file, if any exists?
                    continue

                payload_file = self.root_path / 'features' / 'requests' / variable_value

                # just some text
                if not payload_file.exists():
                    continue

                start = match.start(1)
                end = match.end(1)

                range = Range(
                    start=Position(line=0, character=0),
                    end=Position(line=0, character=0),
                )

                definitions.append(
                    LocationLink(
                        target_uri=payload_file.as_uri(),
                        target_range=range,
                        target_selection_range=range,
                        origin_selection_range=Range(
                            start=Position(line=params.position.line, character=start),
                            end=Position(line=params.position.line, character=end),
                        ),
                    )
                )

            return definitions if len(definitions) > 0 else None

    def _format_arg_line(self, line: str) -> str:
        try:
            argument, description = line.split(':', 1)
            arg_name, arg_type = argument.split(' ')
            arg_type = arg_type.replace('(', '').replace(')', '').strip()

            return f'* {arg_name} `{arg_type}`: {description.strip()}'
        except ValueError:
            return f'* {line}'

    def _complete_keyword(
        self, keyword: Optional[str], document: Document
    ) -> List[CompletionItem]:
        items: List[CompletionItem] = []
        if len(document.source.strip()) < 1:
            keywords = ['Feature']
        else:
            if 'Scenario:' not in document.source:
                keywords = ['Scenario']
            else:
                keywords = self.keywords.copy()

            for keyword_once in self.keywords_once:
                if f'{keyword_once}:' not in document.source:
                    keywords.append(keyword_once)

            # check for partial matches
            if keyword is not None:
                keywords = cast(
                    List[str],
                    list(
                        filter(lambda k: keyword.strip().lower() in k.lower(), keywords)  # type: ignore
                    ),
                )

        for keyword in sorted(keywords):
            items.append(
                CompletionItem(
                    label=keyword,
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
                )
            )

        return items

    def _complete_step(
        self,
        keyword: str,
        expression: Optional[str],
    ) -> List[CompletionItem]:
        if keyword in self.keyword_any:
            steps = [
                step for keyword_steps in self.steps.values() for step in keyword_steps
            ]
        else:
            steps = self.steps.get(keyword.lower(), [])

        matched_steps: List[CompletionItem]

        if expression is None or len(expression) < 1:
            matched_steps = [
                CompletionItem(
                    label=step,
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
                )
                for step in steps
            ]
        else:
            # 1. exact matching
            matched_steps_1: Set[str] = set(filter(lambda s: s.startswith(expression), steps))  # type: ignore

            matched_steps_2: Set[str] = set()
            matched_steps_3: Set[str] = set()

            if len(matched_steps_1) < 1 or ' ' not in expression:
                # 2. close enough matching
                matched_steps_2 = set(filter(lambda s: expression in s, steps))  # type: ignore

                # 3. "fuzzy" matching
                matched_steps_3 = set(
                    get_close_matches(expression, steps, len(steps), 0.6)
                )

            # keep order so that 1. matches comes before 2. matches etc.
            matched_steps_container: Dict[str, CompletionItem] = {}

            for matched_step in itertools.chain(
                matched_steps_1, matched_steps_2, matched_steps_3
            ):
                input_matches = re.finditer(
                    r'"([^"]*)"', expression, flags=re.MULTILINE
                )
                output_matches = re.finditer(
                    r'"([^"]*)"', matched_step, flags=re.MULTILINE
                )

                # suggest step with already entetered variables in their correct place
                if input_matches and output_matches:
                    offset = 0
                    for input_match, output_match in zip(input_matches, output_matches):
                        matched_step = f'{matched_step[0:output_match.start()+offset]}"{input_match.group(1)}"{matched_step[output_match.end()+offset:]}'
                        offset += len(input_match.group(1))

                preselect: bool = False
                if ' ' in expression:
                    insert_text = matched_step.replace(expression, '')
                else:
                    insert_text = matched_step

                # do not suggest the step that is already written
                if matched_step == expression:
                    continue
                elif matched_step == insert_text:  # exact match, preselect it
                    preselect = True

                # if typed expression ends with whitespace, do not insert text starting with a whitespace
                if expression[-1] == ' ':
                    insert_text = insert_text.strip()

                if '""' in insert_text:
                    snippet_matches = re.finditer(
                        r'""',
                        insert_text,
                        flags=re.MULTILINE,
                    )

                    offset = 0
                    for index, snippet_match in enumerate(snippet_matches, start=1):
                        snippet_placeholder = f'${index}'
                        insert_text = f'{insert_text[0:snippet_match.start()+offset]}"{snippet_placeholder}"{insert_text[snippet_match.end()+offset:]}'
                        offset += len(snippet_placeholder)

                    insert_text_format = InsertTextFormat.Snippet
                else:
                    insert_text_format = InsertTextFormat.PlainText

                matched_steps_container.update(
                    {
                        matched_step: CompletionItem(
                            label=matched_step,
                            kind=CompletionItemKind.Function,
                            tags=None,
                            detail=None,
                            documentation=self._find_help(f'{keyword} {matched_step}'),
                            deprecated=False,
                            preselect=preselect,
                            sort_text=None,
                            filter_text=None,
                            insert_text=insert_text,
                            insert_text_format=insert_text_format,
                            insert_text_mode=None,
                            text_edit=None,
                            additional_text_edits=None,
                            commit_characters=None,
                            command=None,
                            data=None,
                        )
                    }
                )  # type: ignore

            matched_steps = list(matched_steps_container.values())

        return matched_steps

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

    def _compile_inventory(self, root_path: Path, project_name: str) -> None:
        self.logger.debug('creating step registry')
        self.behave_steps = load_step_registry(root_path / 'features' / 'steps')

        try:
            self.normalizer = create_step_normalizer()
        except ValueError as e:
            message = str(e)
            self.logger.error(message)
            self.show_message(message, msg_type=MessageType.Error)

        self._compile_step_inventory()

        total_steps = 0
        for steps in self.steps.values():
            total_steps += len(steps)

        self._compile_keyword_inventory()
        message = f'found {len(self.keywords)} keywords and {total_steps} steps for grizzly project {project_name}'
        self.logger.debug(message)
        self.show_message(message)

    def _compile_step_inventory(self) -> None:
        for keyword, steps in self.behave_steps.items():
            normalized_steps_all: List[str] = []
            for step in steps:
                normalized_steps = self._normalize_step_expression(step)

                for normalized_step in normalized_steps:
                    help = getattr(step.func, '__doc__', None)

                    if help is not None:
                        self.help.update({normalized_step: clean_help(help)})

                normalized_steps_all += normalized_steps

            self.steps.update({keyword: normalized_steps_all})

    def _compile_keyword_inventory(self) -> None:
        self.keywords = ['Scenario'] + self.keyword_any[:-1]

        language_en = languages.get('en', {})
        for keyword in self.steps.keys():
            for value in language_en.get(keyword, []):
                value = value.strip()
                if value in [u'*']:
                    continue

                self.keywords.append(value.strip())

    def _current_line(self, uri: str, position: Position) -> str:
        document = self.workspace.get_document(uri)
        content = document.source
        line = content.split('\n')[position.line]

        return line

    def _find_help(self, line: str) -> Optional[str]:
        _, step = get_step_parts(line)

        if step is None:
            return None

        step_help = self.help.get(step.strip(), None)

        if step_help is None:
            possible_help = {
                possible_step: help
                for possible_step, help in self.help.items()
                if possible_step.startswith(step)
            }

            if len(possible_help) < 1:
                return None

            step_help = possible_help[sorted(possible_help.keys(), reverse=True)[0]]

            if self.markup_kind == MarkupKind.PlainText:
                # @TODO: normalize markdown to plain text
                pass

        return step_help
