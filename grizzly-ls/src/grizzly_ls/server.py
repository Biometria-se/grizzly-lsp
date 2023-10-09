from __future__ import annotations

import itertools
import logging
import platform
import signal
import re
import sys

from os import environ, linesep
from os.path import pathsep, sep
from typing import Any, Tuple, Dict, List, Union, Optional, Set, Callable, cast
from types import FrameType
from pathlib import Path
from behave.matchers import ParseMatcher
from venv import create as venv_create
from tempfile import gettempdir
from difflib import get_close_matches
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname
from pip._internal.configuration import Configuration as PipConfiguration
from pip._internal.exceptions import ConfigurationError as PipConfigurationError
from tokenize import tokenize, NAME, OP, TokenError, TokenInfo
from io import BytesIO
from dataclasses import dataclass, field

import gevent.monkey  # type: ignore

from pygls.server import LanguageServer
from pygls.workspace import Document
from pygls.capabilities import get_capability
from lsprotocol.types import (
    INITIALIZE,
    WORKSPACE_DID_CHANGE_CONFIGURATION,
    TEXT_DOCUMENT_HOVER,
    TEXT_DOCUMENT_DEFINITION,
    TEXT_DOCUMENT_COMPLETION,
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind,
    InitializeParams,
    DefinitionParams,
    MessageType,
    Hover,
    HoverParams,
    InsertTextFormat,
    DidChangeConfigurationParams as WorkspaceDidChangeConfigurationParams,
    Position,
    MarkupContent,
    MarkupKind,
    Range,
    LocationLink,
    TextEdit,
)

from behave.i18n import languages

from .text import Normalizer, get_step_parts, clean_help
from .utils import (
    create_step_normalizer,
    load_step_registry,
    run_command,
)
from .progress import Progress
from . import __version__


@dataclass
class Step:
    keyword: str
    expression: str
    func: Callable[..., None]
    help: Optional[str] = field(default=None)


class GrizzlyLanguageServer(LanguageServer):
    FEATURE_INSTALL = 'grizzly-ls/install'

    logger: logging.Logger = logging.getLogger(__name__)

    variable_pattern: re.Pattern[str] = re.compile(
        r'(.*ask for value of variable "([^"]*)"$|.*value for variable "([^"]*)" is ".*?"$)'
    )

    root_path: Path
    index_url: Optional[str]
    behave_steps: Dict[str, List[ParseMatcher]]
    steps: Dict[str, List[Step]]
    keywords: List[str]
    keywords_once: List[str] = []
    keywords_any: List[str] = []
    keywords_headers: List[str] = []
    client_settings: Dict[str, Any]

    _language: str
    localizations: Dict[str, List[str]]

    normalizer: Normalizer

    markup_kind: MarkupKind

    def show_message(
        self, message: str, msg_type: Optional[MessageType] = MessageType.Info
    ) -> None:
        if msg_type == MessageType.Info:
            log_method = self.logger.info
        elif msg_type == MessageType.Error:
            log_method = self.logger.error
        elif msg_type == MessageType.Warning:
            log_method = self.logger.warning
        else:
            log_method = self.logger.debug

        log_method(message)
        super().show_message(message, msg_type=msg_type)  # type: ignore

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(name='grizzly-ls', version=__version__, *args, **kwargs)  # type: ignore

        self.index_url = environ.get('PIP_EXTRA_INDEX_URL', None)
        self.behave_steps = {}
        self.steps = {}
        self.keywords = []
        self.markup_kind = MarkupKind.Markdown  # assume, until initialized request
        self.language = 'en'  # assumed default

        # monkey patch functions to short-circuit them (causes problems in this context)
        gevent.monkey.patch_all = lambda: None

        def _signal(signum: Union[int, signal.Signals], frame: FrameType) -> None:
            return

        signal.signal = _signal  # type: ignore
        self.client_settings = {}

        @self.feature(self.FEATURE_INSTALL)
        def install(params: Dict[str, Any]) -> None:
            """
            See https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#initialize

            > Until the server has responded to the initialize request with an InitializeResult, the client must not send any
            > additional requests or notifications to the server. In addition the server is not allowed to send any requests
            > or notifications to the client until it has responded with an InitializeResult

            This custom feature handles being able to send progress report of the, slow, process of installing dependencies needed
            for it to function properly on the project it is being used.
            """
            self.logger.debug(f'{self.FEATURE_INSTALL}: installing {params=}')

            with Progress(self.progress, 'grizzly-ls') as progress:
                # <!-- should a virtual environment be used?
                use_venv = self.client_settings.get('use_virtual_environment', True)
                executable = 'python3' if use_venv else sys.executable
                # // -->

                self.logger.debug(f'workspace root: {self.root_path}')

                env = environ.copy()
                project_name = self.root_path.stem

                virtual_environment: Optional[Path] = None
                has_venv: bool = False

                if use_venv:
                    virtual_environment = (
                        Path(gettempdir()) / f'grizzly-ls-{project_name}'
                    )
                    has_venv = virtual_environment.exists()

                    self.logger.debug(
                        f'looking for venv at {virtual_environment}, {has_venv=}'
                    )

                    if not has_venv:
                        self.logger.debug(
                            f'creating virtual environment: {virtual_environment}'
                        )
                        self.show_message(
                            'creating virtual environment for language server, this could take a while'
                        )
                        try:
                            progress.report('creating venv', 33)
                            venv_create(str(virtual_environment), with_pip=True)
                        except:
                            self.show_message('failed to create virtual environment')
                            return

                    if platform.system() == 'Windows':  # pragma: no cover
                        bin_dir = 'Scripts'
                    else:
                        bin_dir = 'bin'

                    paths = [
                        str(virtual_environment / bin_dir),
                        env.get('PATH', ''),
                    ]
                    env.update(
                        {
                            'PATH': pathsep.join(paths),
                            'VIRTUAL_ENV': str(virtual_environment),
                            'PYTHONPATH': str(self.root_path / 'features'),
                        }
                    )

                    if self.index_url is not None:
                        index_url_parsed = urlparse(self.index_url)
                        if (
                            index_url_parsed.username is None
                            or index_url_parsed.password is None
                        ):
                            self.show_message(
                                'global.index-url does not contain username and/or password, check your configuration!',
                                msg_type=MessageType.Error,
                            )
                            return

                        env.update(
                            {
                                'PIP_EXTRA_INDEX_URL': self.index_url,
                            }
                        )

                requirements_file = self.root_path / 'requirements.txt'
                if not requirements_file.exists():
                    self.show_message(
                        f'project "{project_name}" does not have a requirements.txt in {self.root_path}',
                        msg_type=MessageType.Error,
                    )
                    return

                project_age_file = (
                    Path(gettempdir()) / f'grizzly-ls-{project_name}' / '.age'
                )

                # pip install (slow operation) if:
                # - age file does not exist
                # - requirements file has been modified since age file was last touched
                if not project_age_file.exists() or (
                    requirements_file.lstat().st_mtime
                    > project_age_file.lstat().st_mtime
                ):
                    action = 'install' if not project_age_file.exists() else 'upgrade'

                    self.logger.debug(f'{action} from {requirements_file}')

                    # <!-- install dependencies
                    progress.report(f'{action} dependencies', 50)

                    rc, output = run_command(
                        [
                            executable,
                            '-m',
                            'pip',
                            'install',
                            '--upgrade',
                            '-r',
                            str(requirements_file),
                        ],
                        env=env,
                    )

                    for line in output:
                        if line.strip().startswith('ERROR:'):
                            _, line = line.split(' ', 1)
                            log_method = self.logger.error
                        elif rc == 0:
                            log_method = self.logger.debug
                        else:
                            log_method = self.logger.warning

                        if len(line.strip()) > 1:
                            log_method(line.strip())

                    self.logger.debug(f'{action} done {rc=}')

                    if rc != 0:
                        self.show_message(
                            f'failed to {action} from {requirements_file}',
                            msg_type=MessageType.Error,
                        )
                        return

                    project_age_file.parent.mkdir(parents=True, exist_ok=True)
                    project_age_file.touch()
                    # // -->

                if use_venv and virtual_environment is not None:
                    # modify sys.path to use modules from virtual environment when compiling inventory
                    venv_sys_path = (
                        virtual_environment
                        / 'lib'
                        / f'python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
                    )
                    sys.path.append(str(venv_sys_path))

                try:
                    # <!-- compile inventory
                    progress.report('compile inventory', 85)
                    self._compile_inventory(self.root_path, project_name)
                    # // ->
                except ModuleNotFoundError:
                    self.show_message(
                        'failed to create step inventory', msg_type=MessageType.Error
                    )
                    return
                finally:
                    if use_venv and virtual_environment is not None:
                        # always restore to original value
                        sys.path.pop()

        @self.feature(INITIALIZE)
        def initialize(params: InitializeParams) -> None:
            if params.root_path is None and params.root_uri is None:
                self.show_message(
                    'neither root_path or root uri was received from client',
                    msg_type=MessageType.Error,
                )
                return

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

            client_settings = params.initialization_options
            if client_settings is not None:
                self.client_settings = cast(Dict[str, Any], client_settings)

            markup_supported: List[MarkupKind] = get_capability(
                self.client_capabilities,
                'text_document.completion.completion_item.documentation_format',
                [MarkupKind.Markdown],
            )
            if len(markup_supported) < 1:
                self.markup_kind = MarkupKind.PlainText
            else:
                self.markup_kind = markup_supported[0]

            # <!-- set index url
            # no index-url specified as argument, check if we have it in pip configuration
            if self.index_url is None:
                pip_config = PipConfiguration(isolated=False)
                try:
                    pip_config.load()
                    self.index_url = pip_config.get_value('global.index-url')
                except PipConfigurationError:
                    pass

            # no index-url specified in pip config, check if we have it in extension configuration
            if self.index_url is None:
                self.index_url = self.client_settings.get('pip_extra_index_url', None)
                if self.index_url is not None and len(self.index_url.strip()) < 1:
                    self.index_url = None

            self.logger.debug(f'{self.index_url=}')
            # // -->

            # <!-- set variable pattern
            variable_patterns = self.client_settings.get('variable_pattern', [])
            if len(variable_patterns) > 0:
                # validate and normalize patterns
                normalized_variable_patterns: Set[str] = set()
                for variable_pattern in variable_patterns:
                    try:
                        original_variable_pattern = variable_pattern
                        if not variable_pattern.startswith(
                            '.*'
                        ) and not variable_pattern.startswith('^'):
                            variable_pattern = f'.*{variable_pattern}'

                        if not variable_pattern.startswith('^'):
                            variable_pattern = f'^{variable_pattern}'

                        if not variable_pattern.endswith('$'):
                            variable_pattern = f'{variable_pattern}$'

                        self.logger.error(
                            f'{original_variable_pattern} -> {variable_pattern}'
                        )

                        pattern = re.compile(variable_pattern)

                        if pattern.groups != 1:
                            self.show_message(
                                f'variable pattern "{original_variable_pattern}" contains {pattern.groups} match groups, it must be exactly one'
                            )
                            return

                        normalized_variable_patterns.add(variable_pattern)
                    except:
                        self.show_message(
                            f'variable pattern "{variable_pattern}" is not valid, check grizzly.variable_pattern setting',
                            msg_type=MessageType.Error,
                        )
                        return

                variable_pattern = f'({"|".join(normalized_variable_patterns)})'
                self.variable_pattern = re.compile(variable_pattern)
            # // -->

        @self.feature(TEXT_DOCUMENT_COMPLETION)
        def completion(params: CompletionParams) -> CompletionList:
            items: List[CompletionItem] = []

            if len(self.steps.values()) < 1:
                self.show_message('no steps in inventory', msg_type=MessageType.Error)
            else:
                line = self._current_line(params.text_document.uri, params.position)

                document = self.workspace.get_text_document(params.text_document.uri)

                self.language = self._find_language(document.source)

                trigger = line[: params.position.character]

                variable_name_trigger = self.get_variable_name_trigger(trigger)

                self.logger.debug(
                    f'{line=}, {params.position=}, {trigger=}, {variable_name_trigger=}'
                )

                if variable_name_trigger is not None and variable_name_trigger[0]:
                    _, partial_variable_name = variable_name_trigger
                    items = self._complete_variable_name(
                        line,
                        document,
                        params.position,
                        partial=partial_variable_name,
                    )
                else:
                    keyword, text = get_step_parts(line)
                    self.logger.debug(f'{keyword=}, {text=}, {self.keywords=}')

                    if keyword is not None and keyword in self.keywords:
                        items = self._complete_step(keyword, params.position, text)
                    else:
                        items = self._complete_keyword(
                            keyword, params.position, document
                        )

            return CompletionList(
                is_incomplete=False,
                items=items,
            )

        @self.feature(WORKSPACE_DID_CHANGE_CONFIGURATION)
        def workspace_did_change_configuration(
            params: WorkspaceDidChangeConfigurationParams,
        ) -> None:
            self.logger.debug(f'{WORKSPACE_DID_CHANGE_CONFIGURATION}: {params=}')

        @self.feature(TEXT_DOCUMENT_HOVER)
        def hover(params: HoverParams) -> Optional[Hover]:
            hover: Optional[Hover] = None
            help_text: Optional[str] = None
            current_line = self._current_line(params.text_document.uri, params.position)
            keyword, step = get_step_parts(current_line)

            self.logger.debug(f'{keyword=}, {step=}')

            abort: bool = False

            try:
                abort = (
                    step is None
                    or keyword is None
                    or (
                        self._get_language_key(keyword) not in self.steps
                        and keyword not in self.keywords_any
                    )
                )
            except:
                abort = True

            if abort or keyword is None:
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

        @self.feature(TEXT_DOCUMENT_DEFINITION)
        def definition(params: DefinitionParams) -> Optional[List[LocationLink]]:
            current_line = self._current_line(params.text_document.uri, params.position)
            definitions: List[LocationLink] = []

            file_url_definitions = self._get_file_url_definition(params, current_line)
            step_definition = self._get_step_definition(params, current_line)

            if len(file_url_definitions) > 0:
                definitions = file_url_definitions
            elif step_definition is not None:
                definitions = [step_definition]

            return definitions if len(definitions) > 0 else None

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        if not hasattr(self, '_language') or self._language != value:
            self.logger.info(f'language detected: "{value}"')
            self._language = value
            self._compile_keyword_inventory()

    def get_variable_name_trigger(
        self, trigger: str
    ) -> Optional[Tuple[bool, Optional[str]]]:
        self.logger.debug(f'{trigger=}')
        partial_variable_name: Optional[str] = None

        token_list = self._get_tokens(trigger)

        tokens_reversed = list(reversed(token_list))

        for index, token in enumerate(tokens_reversed):
            self.logger.debug(f'{index=}, {token=}')
            if index == 0 and token.type == NAME:
                partial_variable_name = token.string
                continue

            try:
                next_token = tokens_reversed[index + 1]
                if (
                    token.type == OP
                    and token.string == '{'
                    and next_token.type == OP
                    and next_token.string == '{'
                ):
                    return (
                        True,
                        partial_variable_name,
                    )
            except IndexError:  # no variable name...
                continue

        return None

    def _get_step_definition(
        self, params: DefinitionParams, current_line: str
    ) -> Optional[LocationLink]:
        step_definition: Optional[LocationLink] = None

        keyword, expression = get_step_parts(current_line)

        if keyword is None or expression is None:
            return None

        expression = re.sub(r'"[^"]*"', '""', expression)
        for steps in self.steps.values():
            for step in steps:
                if step.expression != expression:
                    continue

                import inspect

                file_location = inspect.getfile(step.func)
                _, lineno = inspect.getsourcelines(step.func)
                self.logger.debug(f'!! {step=}, {file_location=}, {lineno=}')
                range = Range(
                    start=Position(line=lineno, character=0),
                    end=Position(line=lineno, character=0),
                )
                step_definition = LocationLink(
                    target_uri=Path(file_location).as_uri(),
                    target_range=range,
                    target_selection_range=range,
                    origin_selection_range=Range(
                        start=Position(
                            line=params.position.line,
                            character=(len(current_line) - len(current_line.lstrip())),
                        ),
                        end=Position(
                            line=params.position.line,
                            character=len(current_line),
                        ),
                    ),
                )

                # we have found what we are looking for
                break

        return step_definition

    def _get_file_url_definition(
        self,
        params: DefinitionParams,
        current_line: str,
    ) -> List[LocationLink]:
        document = self.workspace.get_text_document(params.text_document.uri)
        document_directory = Path(document.path).parent
        definitions: List[LocationLink] = []
        matches = re.finditer(r'"([^"]*)"', current_line, re.MULTILINE)

        for variable_match in matches:
            variable_value = variable_match.group(1)

            if 'file://' in variable_value:
                file_match = re.search(r'.*(file:\/\/)([^\$]*)', variable_value)
                if not file_match:
                    continue
                file_url = f'{file_match.group(1)}{file_match.group(2)}'

                if sys.platform == 'win32':
                    file_url = file_url.replace('\\', '/')

                file_parsed = urlparse(file_url)

                # relativ or absolute?
                if file_parsed.netloc == '.':  # relative!
                    relative_path = file_parsed.path
                    if relative_path.startswith('/'):
                        relative_path = relative_path[1:]

                    payload_file = document_directory / relative_path
                else:  # absolute!
                    payload_file = Path(f'{file_parsed.netloc}{file_parsed.path}')

                start_offset = file_match.start(1)
                end_offset = -1 if variable_value.endswith('$') else 0
            else:
                # this is quite grizzly specific...
                payload_file = self.root_path / 'features' / 'requests' / variable_value
                start_offset = 0
                end_offset = 0

            # just some text
            if not payload_file.exists():
                continue

            start = variable_match.start(1) + start_offset
            end = variable_match.end(1) + end_offset

            # don't add link definition if cursor is out side of range for that link
            if params.position.character >= start and params.position.character <= end:
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

        return definitions

    def _get_tokens(self, text: str) -> List[TokenInfo]:
        tokens: List[TokenInfo] = []

        # convert generator to list
        try:
            for token in tokenize(BytesIO(text.encode('utf8')).readline):
                tokens.append(token)
        except TokenError as e:
            if 'EOF in multi-line statement' not in str(e):
                raise

        return tokens

    def _format_arg_line(self, line: str) -> str:
        try:
            argument, description = line.split(':', 1)
            arg_name, arg_type = argument.split(' ')
            arg_type = arg_type.replace('(', '').replace(')', '').strip()

            return f'* {arg_name} `{arg_type}`: {description.strip()}'
        except ValueError:
            return f'* {line}'

    def _find_language(self, document: str) -> str:
        language: str = 'en'

        for line in document.split(linesep):
            line = line.strip()
            if line.startswith('# language: '):
                _, language = line.strip().split(': ', 1)
                break

        return language.strip()

    def _complete_keyword(
        self, keyword: Optional[str], position: Position, document: Document
    ) -> List[CompletionItem]:
        items: List[CompletionItem] = []
        if len(document.source.strip()) < 1:
            keywords = [*self.localizations.get('feature', [])]
        else:
            scenario_keywords = [
                *self.localizations.get('scenario', []),
                *self.localizations.get('scenario_outline', []),
            ]

            if not any(
                [
                    scenario_keyword in document.source
                    for scenario_keyword in scenario_keywords
                ]
            ):
                keywords = scenario_keywords
            else:
                keywords = self.keywords.copy()

            for keyword_once in self.keywords_once:
                if f'{keyword_once}:' not in document.source:
                    keywords.append(keyword_once)

            # check for partial matches
            if keyword is not None:
                keywords = [k for k in keywords if keyword.strip().lower() in k.lower()]

        for suggested_keyword in sorted(keywords):
            start = Position(
                line=position.line, character=position.character - len(keyword or '')
            )
            if suggested_keyword in self.keywords_headers:
                suffix = ': '
            else:
                suffix = ' '

            text_edit = TextEdit(
                range=Range(
                    start=start,
                    end=position,
                ),
                new_text=f'{suggested_keyword}{suffix}',
            )
            items.append(
                CompletionItem(
                    label=suggested_keyword,
                    kind=CompletionItemKind.Keyword,
                    deprecated=False,
                    text_edit=text_edit,
                )
            )

        return items

    def _complete_variable_name(
        self,
        line: str,
        document: Document,
        position: Position,
        *,
        partial: Optional[str] = None,
    ) -> List[CompletionItem]:
        items: List[CompletionItem] = []

        # find `Scenario:` before current position
        lines = document.source.splitlines()
        before_lines = reversed(lines[0 : position.line])

        for before_line in before_lines:
            match = self.variable_pattern.match(before_line)

            if match:
                variable_name = match.group(2) or match.group(3)

                if variable_name is None:
                    continue

                if partial is not None and not variable_name.startswith(partial):
                    continue

                text_edit: Optional[TextEdit] = None

                if partial is not None:
                    prefix = ''
                else:
                    prefix = '' if line[: position.character].endswith(' ') else ' '

                suffix = (
                    '"'
                    if not line.rstrip().endswith('"') and line.count('"') % 2 != 0
                    else ''
                )
                affix = (
                    '' if line[position.character :].strip().startswith('}}') else '}}'
                )
                affix_suffix = (
                    ''
                    if not line[position.character :].startswith('}}') and affix != '}}'
                    else ' '
                )
                new_text = f'{prefix}{variable_name}{affix_suffix}{affix}{suffix}'

                start = Position(
                    line=position.line,
                    character=position.character - len(partial or ''),
                )
                text_edit = TextEdit(
                    range=Range(
                        start=start,
                        end=Position(
                            line=position.line,
                            character=start.character + len(partial or ''),
                        ),
                    ),
                    new_text=new_text,
                )

                self.logger.debug(
                    f'{line=}, {variable_name=}, {partial=}, {text_edit=}'
                )

                items.append(
                    CompletionItem(
                        label=variable_name,
                        kind=CompletionItemKind.Variable,
                        deprecated=False,
                        text_edit=text_edit,
                    )
                )
            elif any(
                [
                    scenario_keyword in before_line
                    for scenario_keyword in self.localizations.get('scenario', [])
                ]
            ):
                break

        return items

    def _complete_step(
        self,
        keyword: str,
        position: Position,
        expression: Optional[str],
    ) -> List[CompletionItem]:
        if keyword in self.keywords_any:
            steps = list(
                set(
                    [
                        step.expression
                        for keyword_steps in self.steps.values()
                        for step in keyword_steps
                    ]
                )
            )
        else:
            key = self._get_language_key(keyword)
            steps = [
                step.expression
                for step in self.steps.get(key, []) + self.steps.get('step', [])
            ]

        matched_steps: List[CompletionItem] = []
        matched_steps_1: Set[str]
        matched_steps_2: Set[str] = set()
        matched_steps_3: Set[str] = set()

        if expression is None or len(expression) < 1:
            matched_steps_1 = set(steps)
        else:
            # remove any user values enclosed with double-quotes
            expression_shell = re.sub(r'"[^"]*"', '""', expression)

            # 1. exact matching
            matched_steps_1: Set[str] = set(filter(lambda s: s.startswith(expression_shell), steps))  # type: ignore

            if len(matched_steps_1) < 1 or ' ' not in expression:
                # 2. close enough matching
                matched_steps_2 = set(filter(lambda s: expression_shell in s, steps))  # type: ignore

                # 3. "fuzzy" matching
                matched_steps_3 = set(
                    get_close_matches(expression_shell, steps, len(steps), 0.6)
                )

        # keep order so that 1. matches comes before 2. matches etc.
        matched_steps_container: Dict[str, CompletionItem] = {}

        input_matches = list(
            re.finditer(r'"([^"]*)"', expression or '', flags=re.MULTILINE)
        )

        for matched_step in itertools.chain(
            matched_steps_1, matched_steps_2, matched_steps_3
        ):
            output_matches = list(
                re.finditer(r'"([^"]*)"', matched_step, flags=re.MULTILINE)
            )

            # suggest step with already entetered variables in their correct place
            if input_matches and output_matches:
                offset = 0
                for input_match, output_match in zip(input_matches, output_matches):
                    matched_step = f'{matched_step[0:output_match.start()+offset]}"{input_match.group(1)}"{matched_step[output_match.end()+offset:]}'
                    offset += len(input_match.group(1))

            preselect: bool = False
            if (
                expression is not None
                and len(expression.strip()) > 0
                and ' ' in expression
            ):
                # only insert the part of the step that has not already been written, up until last space, since vscode
                # seems to insert text word wise
                new_text = matched_step.replace(expression, '')
                if not new_text.startswith(' ') and new_text.strip().count(' ') < 1:
                    try:
                        _, new_text = matched_step.rsplit(' ', 1)
                    except:
                        pass
            else:
                new_text = matched_step

            # do not suggest the step that is already written
            if matched_step == expression:
                continue
            elif matched_step == new_text:  # exact match, preselect it
                preselect = True

            # if typed expression ends with whitespace, do not insert text starting with a whitespace
            if (
                expression is not None
                and len(expression.strip()) > 0
                and expression[-1] == ' '
                and expression[-2] != ' '
                and new_text[0] == ' '
            ):
                new_text = new_text[1:]

            self.logger.debug(f'{expression=}, {new_text=}, {matched_step=}')

            if '""' in new_text:
                snippet_matches = re.finditer(
                    r'""',
                    new_text,
                    flags=re.MULTILINE,
                )

                offset = 0
                for index, snippet_match in enumerate(snippet_matches, start=1):
                    snippet_placeholder = f'${index}'
                    new_text = f'{new_text[0:snippet_match.start()+offset]}"{snippet_placeholder}"{new_text[snippet_match.end()+offset:]}'
                    offset += len(snippet_placeholder)

                insert_text_format = InsertTextFormat.Snippet
            else:
                insert_text_format = InsertTextFormat.PlainText

            text_edit = TextEdit(
                range=Range(start=position, end=position),
                new_text=new_text,
            )

            matched_steps_container.update(
                {
                    matched_step: CompletionItem(
                        label=matched_step,
                        kind=CompletionItemKind.Function,
                        documentation=self._find_help(f'{keyword} {matched_step}'),
                        deprecated=False,
                        preselect=preselect,
                        insert_text_format=insert_text_format,
                        text_edit=text_edit,
                    )
                }
            )  # type: ignore

            matched_steps = list(matched_steps_container.values())

        return matched_steps

    def _get_language_key(self, keyword: str) -> str:
        if keyword in self.keywords_any:
            return 'step'

        for key, values in self.localizations.items():
            if keyword in values:
                return key

        raise ValueError(f'"{keyword}" is not a valid keyword')

    def _normalize_step_expression(self, step: Union[ParseMatcher, str]) -> List[str]:
        if isinstance(step, ParseMatcher):
            pattern = step.pattern
        else:
            pattern = step

        patterns, errors = self.normalizer(pattern)

        if len(errors) > 0:
            for message in errors:
                self.show_message(message, msg_type=MessageType.Error)

        return patterns

    def _compile_inventory(self, root_path: Path, project_name: str) -> None:
        self.logger.debug('creating step registry')

        try:
            self.behave_steps = load_step_registry(
                [path.parent for path in root_path.rglob('*.py')]
            )
        except ModuleNotFoundError:
            self.show_message(
                'unable to load behave step expressions', msg_type=MessageType.Error
            )
            return

        try:
            self.normalizer = create_step_normalizer()
        except ValueError as e:
            self.show_message(str(e), msg_type=MessageType.Error)
            return

        self._compile_step_inventory()

        total_steps = 0
        for steps in self.steps.values():
            total_steps += len(steps)

        self._compile_keyword_inventory()
        self.show_message(
            f'found {len(self.keywords)} keywords and {total_steps} steps in "{project_name}"'
        )

    def _compile_step_inventory(self) -> None:
        for keyword, steps in self.behave_steps.items():
            normalized_steps_all: List[Step] = []
            for step in steps:
                normalized_steps = self._normalize_step_expression(step)
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

            self.steps.update({keyword: normalized_steps_all})

    def _compile_keyword_inventory(self) -> None:
        self.localizations = languages.get(self.language, {})
        if self.localizations == {}:
            raise ValueError(f'unknown language "{self.language}"')

        # localized any keywords
        self.keywords_any = list(
            set(
                [
                    '*',
                    *self.localizations.get('but', []),
                    *self.localizations.get('and', []),
                ]
            )
        )

        # localized keywords that should only appear once
        self.keywords_once = list(
            set(
                [
                    *self.localizations.get('feature', []),
                    *self.localizations.get('background', []),
                ]
            )
        )

        self.keywords_headers = []
        for key, values in self.localizations.items():
            if values[0] != u'*':
                self.keywords_headers.extend([*self.localizations.get(key, [])])

        # localized keywords
        self.keywords = list(
            set(
                [
                    *self.localizations.get('scenario', []),
                    *self.localizations.get('scenario_outline', []),
                    *self.localizations.get('examples', []),
                    *self.keywords_any,
                ]
            )
        )
        self.keywords.remove('*')

        for keyword in self.steps.keys():
            for value in self.localizations.get(keyword, []):
                value = value.strip()
                if value in [u'*']:
                    continue

                self.keywords.append(value.strip())

    def _current_line(self, uri: str, position: Position) -> str:
        document = self.workspace.get_text_document(uri)
        content = document.source
        line = content.split('\n')[position.line]

        return line

    def _find_help(self, line: str) -> Optional[str]:
        keyword, expression = get_step_parts(line)

        if expression is None or keyword is None:
            return None

        possible_help: Dict[str, str] = {}

        key = self._get_language_key(keyword)
        expression = re.sub(r'"[^"]*"', '""', expression)

        for steps in self.steps.values():
            for step in steps:
                if step.expression.strip() == expression.strip() and (
                    key == keyword or key == 'step'
                ):
                    return step.help
                elif step.expression.startswith(expression) and step.help is not None:
                    possible_help.update({step.expression: step.help})

        if len(possible_help) < 1:
            return None

        return possible_help[sorted(possible_help.keys(), reverse=True)[0]]
