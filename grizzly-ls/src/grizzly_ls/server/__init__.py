from __future__ import annotations

import platform
import signal
import re
import sys

from os import environ
from os.path import pathsep, sep
from typing import (
    Any,
    Deque,
    Tuple,
    Dict,
    List,
    Union,
    Optional,
    Set,
    cast,
)
from types import FrameType
from pathlib import Path
from behave.matchers import ParseMatcher
from venv import create as venv_create
from tempfile import gettempdir
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname
from pip._internal.configuration import Configuration as PipConfiguration  # type: ignore
from pip._internal.exceptions import ConfigurationError as PipConfigurationError  # type: ignore
from time import sleep
from collections import deque
from logging import ERROR

from pygls.server import LanguageServer
from pygls.workspace import TextDocument
from pygls.capabilities import get_capability
from lsprotocol import types as lsp

from grizzly_ls import __version__
from grizzly_ls.text import Normalizer, get_step_parts
from grizzly_ls.utils import run_command, LogOutputChannelLogger
from grizzly_ls.model import Step
from grizzly_ls.constants import FEATURE_INSTALL, COMMAND_REBUILD_INVENTORY, COMMAND_RUN_DIAGNOSTICS, COMMAND_RENDER_GHERKIN, LANGUAGE_ID
from grizzly_ls.text import (
    format_arg_line,
    find_language,
    get_current_line,
)

from .progress import Progress
from .features.completion import (
    get_trigger,
    complete_keyword,
    complete_variable_name,
    complete_step,
    complete_metadata,
    complete_expression,
)
from .features.definition import get_step_definition, get_file_url_definition
from .features.diagnostics import validate_gherkin
from .features.code_actions import generate_quick_fixes
from .inventory import compile_inventory, compile_keyword_inventory
from .commands import render_gherkin


class GrizzlyLanguageServer(LanguageServer):
    logger: LogOutputChannelLogger

    variable_pattern: re.Pattern[str] = re.compile(r'(.*ask for value of variable "([^"]*)"$|.*value for variable "([^"]*)" is ".*?"$)')

    file_ignore_patterns: List[str]
    root_path: Path
    index_url: Optional[str]
    behave_steps: Dict[str, List[ParseMatcher]]
    steps: Dict[str, List[Step]]
    keywords: List[str]
    keywords_once: List[str] = []
    keywords_any: List[str] = []
    keywords_headers: List[str] = []
    keywords_all: List[str] = []
    client_settings: Dict[str, Any]
    startup_messages: Deque[Tuple[str, int]]

    _language: str
    localizations: Dict[str, List[str]]

    normalizer: Normalizer

    markup_kind: lsp.MarkupKind

    def add_startup_error_message(self, message: str) -> None:
        self.startup_messages.append((message, ERROR))

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(name='grizzly-ls', version=__version__, *args, **kwargs)  # type: ignore

        self.logger = LogOutputChannelLogger(self)

        self.index_url = environ.get('PIP_EXTRA_INDEX_URL', None)
        self.behave_steps = {}
        self.steps = {}
        self.keywords = []
        self.markup_kind = lsp.MarkupKind.Markdown  # assume, until initialized request
        self.language = 'en'  # assumed default
        self.file_ignore_patterns = []
        self.startup_messages = deque()

        # monkey patch functions to short-circuit them (causes problems in this context)
        try:
            import gevent.monkey  # type: ignore

            gevent.monkey.patch_all = lambda: None
        except ModuleNotFoundError:
            pass

        def _signal(signum: Union[int, signal.Signals], frame: FrameType) -> None:
            return

        signal.signal = _signal  # type: ignore
        self.client_settings = {}

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        if not hasattr(self, '_language') or self._language != value:
            self._language = value
            compile_keyword_inventory(self)
            name = self.localizations.get('name', ['unknown'])[0]
            self.logger.info(f'language detected: {name} ({value})')

    def get_language_key(self, keyword: str) -> str:
        keyword = keyword.rstrip(' :')

        for key, values in self.localizations.items():
            if keyword in values:
                return key

        raise ValueError(f'"{keyword}" is not a valid keyword for "{self.language}"')

    def get_base_keyword(self, position: lsp.Position, text_document: TextDocument) -> str:
        lines = list(reversed(text_document.source.splitlines()[: position.line + 1]))

        current_line = lines[0]
        base_keyword, _ = get_step_parts(current_line)

        if base_keyword is None:
            raise ValueError(f'unable to get keyword from "{current_line}"')

        base_keyword = base_keyword.rstrip(' :')

        if base_keyword not in self.keywords_any and base_keyword in self.keywords_all:
            return base_keyword

        for line in lines[1:]:
            step_keyword, _ = get_step_parts(line)

            if step_keyword is None:
                continue

            step_keyword = step_keyword.rstrip(' :')

            if step_keyword not in self.keywords_all:
                continue

            if step_keyword not in self.keywords_any:
                return step_keyword

        return base_keyword

    def _normalize_step_expression(self, step: Union[ParseMatcher, str]) -> List[str]:
        if isinstance(step, ParseMatcher):
            pattern = step.pattern
        else:
            pattern = step

        patterns = self.normalizer(pattern)

        return patterns

    def _find_help(self, line: str) -> Optional[str]:
        keyword, expression = get_step_parts(line)

        if expression is None or keyword is None:
            return None

        possible_help: Dict[str, str] = {}

        key = self.get_language_key(keyword)
        expression = re.sub(r'"[^"]*"', '""', expression)

        for steps in self.steps.values():
            for step in steps:
                if step.expression.strip() == expression.strip() and (key == keyword or key == 'step'):
                    return step.help
                elif step.expression.startswith(expression) and step.help is not None:
                    possible_help.update({step.expression: step.help})

        if len(possible_help) < 1:
            return None

        return possible_help[sorted(possible_help.keys(), reverse=True)[0]]


server = GrizzlyLanguageServer()


@server.feature(FEATURE_INSTALL)
def install(ls: GrizzlyLanguageServer, *args: Any) -> None:
    """
    See https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#initialize

    > Until the server has responded to the initialize request with an InitializeResult, the client must not send any
    > additional requests or notifications to the server. In addition the server is not allowed to send any requests
    > or notifications to the client until it has responded with an InitializeResult

    This custom feature handles being able to send progress report of the, slow, process of installing dependencies needed
    for it to function properly on the project it is being used.
    """
    ls.logger.debug(f'{FEATURE_INSTALL}: installing')

    try:
        with Progress(ls.progress, 'grizzly-ls') as progress:
            # <!-- should a virtual environment be used?
            use_venv = ls.client_settings.get('use_virtual_environment', True)
            executable = 'python' if use_venv else sys.executable
            # // -->

            ls.logger.debug(f'workspace root: {ls.root_path}')

            env = environ.copy()
            project_name = ls.root_path.stem

            virtual_environment: Optional[Path] = None
            has_venv: bool = False

            if use_venv:
                virtual_environment = Path(gettempdir()) / f'grizzly-ls-{project_name}'
                has_venv = virtual_environment.exists()

                ls.logger.debug(f'looking for venv at {virtual_environment}, {has_venv=}')

                if not has_venv:
                    ls.logger.logger.debug(f'creating virtual environment: {virtual_environment}')
                    ls.logger.info('creating virtual environment for language server, this could take a while', notify=True)
                    try:
                        progress.report('creating venv', 33)
                        venv_create(str(virtual_environment), with_pip=True)
                    except:
                        ls.logger.exception('failed to create virtual environment', notify=True)
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
                        'PYTHONPATH': str(ls.root_path / 'features'),
                    }
                )

                if ls.index_url is not None:
                    index_url_parsed = urlparse(ls.index_url)
                    if index_url_parsed.username is None or index_url_parsed.password is None:
                        ls.logger.error(
                            'global.index-url does not contain username and/or password, check your configuration!',
                            notify=True,
                        )
                        return

                    env.update(
                        {
                            'PIP_EXTRA_INDEX_URL': ls.index_url,
                        }
                    )

            requirements_file = ls.root_path / 'requirements.txt'
            if not requirements_file.exists():
                ls.logger.error(
                    f'project "{project_name}" does not have a requirements.txt in {ls.root_path}',
                    notify=True,
                )
                return

            project_age_file = Path(gettempdir()) / f'grizzly-ls-{project_name}' / '.age'

            # pip install (slow operation) if:
            # - age file does not exist
            # - requirements file has been modified since age file was last touched
            if not project_age_file.exists() or (requirements_file.lstat().st_mtime > project_age_file.lstat().st_mtime):
                action = 'install' if not project_age_file.exists() else 'upgrade'

                ls.logger.debug(f'{action} from {requirements_file}')

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
                        log_method = ls.logger.error
                    elif rc == 0:
                        log_method = ls.logger.debug
                    else:
                        log_method = ls.logger.warning

                    if len(line.strip()) > 1:
                        log_method(line.strip())

                ls.logger.debug(f'{action} done {rc=}')

                if rc != 0:
                    ls.logger.error(
                        f'failed to {action} from {requirements_file}',
                        notify=True,
                    )
                    return

                project_age_file.parent.mkdir(parents=True, exist_ok=True)
                project_age_file.touch()
                # // -->

            if use_venv and virtual_environment is not None:
                # modify sys.path to use modules from virtual environment when compiling inventory
                venv_sys_path = virtual_environment / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
                sys.path.append(str(venv_sys_path))

            try:
                # <!-- compile inventory
                progress.report('compile inventory', 85)
                compile_inventory(ls)
                # // ->
            except ModuleNotFoundError:
                ls.logger.exception(
                    'failed to create step inventory',
                    notify=True,
                )
                return
            finally:
                if use_venv and virtual_environment is not None:
                    # always restore to original value
                    sys.path.pop()
    except:
        ls.logger.exception('failed to install extension', notify=True)

    try:
        for text_document in ls.workspace.text_documents.values():
            if text_document.language_id != LANGUAGE_ID:
                continue

            diagnostics = validate_gherkin(ls, text_document)
            ls.publish_diagnostics(text_document.uri, diagnostics)  # type: ignore
    except:
        ls.logger.exception('failed to run diagnostics on all opened files', notify=True)


@server.feature(lsp.INITIALIZE)
def initialize(ls: GrizzlyLanguageServer, params: lsp.InitializeParams) -> None:
    run_mode = 'embedded' if environ.get('GRIZZLY_RUN_EMBEDDED', 'false') == 'true' else 'standalone'
    ls.logger.info(f'initializing language server {__version__} ({run_mode})')

    if params.root_path is None and params.root_uri is None:
        ls.logger.error(
            'neither root_path or root uri was received from client',
            notify=True,
        )
        return

    while ls.startup_messages:
        msg, level = ls.startup_messages.popleft()
        ls.logger.log(level, msg, exc_info=False, notify=True)

    try:
        root_path = Path(unquote(url2pathname(urlparse(params.root_uri).path))) if params.root_uri is not None else Path(cast(str, params.root_path))

        # fugly as hell
        if not root_path.exists() and str(root_path)[0:1] == sep and str(root_path)[2] == ':':
            root_path = Path(str(root_path)[1:])

        ls.root_path = root_path

        client_settings = params.initialization_options
        if client_settings is not None:
            ls.client_settings = cast(Dict[str, Any], client_settings)

        markup_supported: List[lsp.MarkupKind] = get_capability(
            ls.client_capabilities,
            'text_document.completion.completion_item.documentation_format',
            [lsp.MarkupKind.Markdown],
        )
        if len(markup_supported) < 1:
            ls.markup_kind = lsp.MarkupKind.PlainText
        else:
            ls.markup_kind = markup_supported[0]

        # <!-- set index url
        # no index-url specified as argument, check if we have it in pip configuration
        if ls.index_url is None:
            pip_config = PipConfiguration(isolated=False)
            try:
                pip_config.load()
                ls.index_url = pip_config.get_value('global.index-url')
            except PipConfigurationError:
                pass

        # no index-url specified in pip config, check if we have it in extension configuration
        if ls.index_url is None:
            ls.index_url = ls.client_settings.get('pip_extra_index_url', None)
            if ls.index_url is not None and len(ls.index_url.strip()) < 1:
                ls.index_url = None

        ls.logger.debug(f'{ls.index_url=}')
        # // -->

        # <!-- set variable pattern
        variable_patterns = ls.client_settings.get('variable_pattern', [])
        if len(variable_patterns) > 0:
            # validate and normalize patterns
            normalized_variable_patterns: Set[str] = set()
            for variable_pattern in variable_patterns:
                try:
                    original_variable_pattern = variable_pattern
                    if not variable_pattern.startswith('.*') and not variable_pattern.startswith('^'):
                        variable_pattern = f'.*{variable_pattern}'

                    if not variable_pattern.startswith('^'):
                        variable_pattern = f'^{variable_pattern}'

                    if not variable_pattern.endswith('$'):
                        variable_pattern = f'{variable_pattern}$'

                    pattern = re.compile(variable_pattern)

                    if pattern.groups != 1:
                        ls.logger.warning(f'variable pattern "{original_variable_pattern}" contains {pattern.groups} match groups, it must be exactly one', notify=True)
                        return

                    normalized_variable_patterns.add(variable_pattern)
                except:
                    ls.logger.exception(
                        f'variable pattern "{variable_pattern}" is not valid, check grizzly.variable_pattern setting',
                        notify=True,
                    )
                    return

            variable_pattern = f'({"|".join(normalized_variable_patterns)})'
            ls.variable_pattern = re.compile(variable_pattern)
        # // -->

        # <!-- set file ignore patterns
        ls.file_ignore_patterns = ls.client_settings.get('file_ignore_patterns', [])
        # // -->

        # <!-- quick fix structure
        quick_fix = ls.client_settings.get('quick_fix', None)
        if quick_fix is None:
            ls.client_settings.update({'quick_fix': {}})
        # // -->

        # <!-- missing step impl template
        step_impl_template = ls.client_settings['quick_fix'].get('step_impl_template', None)
        if step_impl_template is None or len(step_impl_template.strip()) == 0:
            step_impl_template = "@{keyword}(u'{expression}')"
            ls.client_settings['quick_fix'].update({'step_impl_template': step_impl_template})
        # // ->
    except:
        ls.logger.exception('failed to initialize extension', notify=True)


@server.feature(lsp.TEXT_DOCUMENT_COMPLETION)
def text_document_completion(
    ls: GrizzlyLanguageServer,
    params: lsp.CompletionParams,
) -> lsp.CompletionList:
    items: List[lsp.CompletionItem] = []

    if len(ls.steps.values()) < 1:
        ls.logger.error('no steps in inventory', notify=True)
        return lsp.CompletionList(
            is_incomplete=False,
            items=items,
        )

    try:
        text_document = ls.workspace.get_text_document(params.text_document.uri)
        line = get_current_line(text_document, params.position)

        trigger = line[: params.position.character]

        ls.logger.debug(f'{line=}, {params.position=}, {trigger=}')

        for trigger_characters, completion_func in [
            ('{{', complete_variable_name),
            ('{%', complete_expression),
        ]:
            if trigger_characters not in trigger:
                continue

            partial_value = get_trigger(trigger, trigger_characters)
            ls.logger.debug(f'{trigger_characters=}, {partial_value=}')
            if not isinstance(partial_value, bool):
                items = completion_func(ls, line, text_document, params.position, partial=partial_value)
                break

        if len(items) < 1:
            if line.strip().startswith('#'):
                items = complete_metadata(line, params.position)
            else:
                keyword, text = get_step_parts(line)

                if keyword is not None and keyword in ls.keywords:
                    base_keyword = ls.get_base_keyword(params.position, text_document)

                    ls.logger.debug(f'{keyword=}, {base_keyword=}, {text=}, {ls.keywords=}')

                    items = complete_step(ls, keyword, params.position, text, base_keyword=base_keyword)
                else:
                    ls.logger.debug(f'{keyword=}, {text=}, {ls.keywords=}')
                    items = complete_keyword(ls, keyword, params.position, text_document)
    except:
        ls.logger.exception('failed to complete step expression', notify=True)

    return lsp.CompletionList(
        is_incomplete=False,
        items=items,
    )


@server.feature(lsp.WORKSPACE_DID_CHANGE_CONFIGURATION)
def workspace_did_change_configuration(
    ls: GrizzlyLanguageServer,
    params: lsp.DidChangeConfigurationParams,
) -> None:
    ls.logger.debug(f'{lsp.WORKSPACE_DID_CHANGE_CONFIGURATION}: {params=}')  # pragma: no cover


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
def text_document_hover(ls: GrizzlyLanguageServer, params: lsp.HoverParams) -> Optional[lsp.Hover]:
    hover: Optional[lsp.Hover] = None
    help_text: Optional[str] = None
    text_document = ls.workspace.get_text_document(params.text_document.uri)
    current_line = get_current_line(text_document, params.position)
    keyword, step = get_step_parts(current_line)

    ls.logger.debug(f'{keyword=}, {step=}')

    abort: bool = False

    try:
        abort = step is None or keyword is None or (ls.get_language_key(keyword) not in ls.steps and keyword not in ls.keywords_any)
    except:
        abort = True

    if abort or keyword is None:
        return None

    try:
        start = current_line.index(keyword)
        end = len(current_line) - 1

        help_text = ls._find_help(current_line)

        if help_text is None:
            return None

        if 'Args:' in help_text:
            pre, post = help_text.split('Args:', 1)
            text = '\n'.join([format_arg_line(arg_line) for arg_line in post.strip().split('\n')])

            help_text = f'{pre}Args:\n\n{text}\n'

        contents = lsp.MarkupContent(kind=ls.markup_kind, value=help_text)
        range = lsp.Range(
            start=lsp.Position(line=params.position.line, character=start),
            end=lsp.Position(line=params.position.line, character=end),
        )
        hover = lsp.Hover(contents=contents, range=range)
    except:
        ls.logger.exception('failed to get step expression help on hover', notify=True)

    return hover


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def text_document_did_change(ls: GrizzlyLanguageServer, params: lsp.DidChangeTextDocumentParams) -> None:
    text_document = ls.workspace.get_text_document(params.text_document.uri)

    try:
        ls.language = find_language(text_document.source)
    except ValueError:
        ls.language = 'en'


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def text_document_did_open(ls: GrizzlyLanguageServer, params: lsp.DidOpenTextDocumentParams) -> None:
    text_document = ls.workspace.get_text_document(params.text_document.uri)

    if text_document.language_id != LANGUAGE_ID:
        return

    try:
        ls.language = find_language(text_document.source)
    except ValueError:
        ls.language = 'en'

    # if only validating on save, we should definitely do it now
    if ls.client_settings.get('diagnostics_on_save_only', True):
        try:
            diagnostics = validate_gherkin(ls, text_document)
            ls.publish_diagnostics(text_document.uri, diagnostics)  # type: ignore
        except:
            ls.logger.exception('failed to run diagnostics on opened file', notify=True)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def text_document_did_close(ls: GrizzlyLanguageServer, params: lsp.DidCloseTextDocumentParams) -> None:
    # always clear diagnostics when file is closed
    try:
        ls.publish_diagnostics(params.text_document.uri, None)  # type: ignore
    except:
        ls.logger.exception('failed to clear diagnostics for closed file', notify=True)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def text_document_did_save(ls: GrizzlyLanguageServer, params: lsp.DidSaveTextDocumentParams) -> None:
    text_document = ls.workspace.get_text_document(params.text_document.uri)

    if text_document.language_id != LANGUAGE_ID:
        return

    # if only validating on save, we should definitely do it now
    if ls.client_settings.get('diagnostics_on_save_only', True):
        try:
            diagnostics = validate_gherkin(ls, text_document)
            ls.publish_diagnostics(text_document.uri, diagnostics)  # type: ignore
        except:
            ls.logger.exception('failed to run diagnostics on save', notify=True)


@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def text_document_definition(
    ls: GrizzlyLanguageServer,
    params: lsp.DefinitionParams,
) -> Optional[List[lsp.LocationLink]]:
    text_document = ls.workspace.get_text_document(params.text_document.uri)
    current_line = get_current_line(text_document, params.position)
    definitions: List[lsp.LocationLink] = []

    ls.logger.debug(f'{lsp.TEXT_DOCUMENT_DEFINITION}: {params=}')

    try:
        file_url_definitions = get_file_url_definition(ls, params, current_line)

        if len(file_url_definitions) > 0:
            definitions = file_url_definitions
        else:
            step_definition = get_step_definition(ls, params, current_line)
            if step_definition is not None:
                definitions = [step_definition]
    except:
        ls.logger.exception('failed to get document definitions', notify=True)

    return definitions if len(definitions) > 0 else None


@server.feature(
    lsp.TEXT_DOCUMENT_DIAGNOSTIC,
    lsp.DiagnosticOptions(
        identifier='behave',
        inter_file_dependencies=False,
        workspace_diagnostics=True,
    ),
)
def text_document_diagnostic(
    ls: GrizzlyLanguageServer,
    params: lsp.DocumentDiagnosticParams,
) -> lsp.DocumentDiagnosticReport:
    items: List[lsp.Diagnostic] = []
    if not ls.client_settings.get('diagnostics_on_save_only', True):
        try:
            text_document = ls.workspace.get_text_document(params.text_document.uri)
            items = validate_gherkin(ls, text_document)
        except:
            ls.logger.exception('failed to run document diagnostics', notify=True)

    return lsp.RelatedFullDocumentDiagnosticReport(
        items=items,
        kind=lsp.DocumentDiagnosticReportKind.Full,
    )


@server.feature(lsp.WORKSPACE_DIAGNOSTIC)
def workspace_diagnostic(
    ls: GrizzlyLanguageServer,
    params: lsp.WorkspaceDiagnosticParams,
) -> lsp.WorkspaceDiagnosticReport:
    report = lsp.WorkspaceDiagnosticReport(items=[])

    try:
        items: List[lsp.Diagnostic] = []
        try:
            first_text_document = list(ls.workspace.text_documents.keys())[0]
        except:
            raise FileNotFoundError

        text_document = ls.workspace.get_text_document(first_text_document)

        if not ls.client_settings.get('diagnostics_on_save_only', True):
            items = validate_gherkin(ls, text_document)

        report.items = [
            lsp.WorkspaceFullDocumentDiagnosticReport(
                uri=text_document.uri,
                items=items,
                kind=lsp.DocumentDiagnosticReportKind.Full,
            )
        ]
    except FileNotFoundError:
        pass
    except:
        ls.logger.exception('failed to run workspace diagnostics', notify=True)

    return report


@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
def text_document_code_action(
    ls: GrizzlyLanguageServer,
    params: lsp.CodeActionParams,
) -> Optional[List[lsp.CodeAction]]:
    try:
        diagnostics = params.context.diagnostics
        text_document = ls.workspace.get_text_document(params.text_document.uri)

        if len(diagnostics) == 0:
            return None
        else:
            return generate_quick_fixes(ls, text_document, diagnostics)
    except:
        ls.logger.exception('failed to generate quick fixes', notify=True)
        return None


@server.command(COMMAND_REBUILD_INVENTORY)
def command_rebuild_inventory(ls: GrizzlyLanguageServer, *args: Any) -> None:
    ls.logger.info(f'executing command: {COMMAND_REBUILD_INVENTORY}')
    try:
        sleep(1.0)  # uuhm, some race condition?
        compile_inventory(ls)

        for text_document in ls.workspace.text_documents.values():
            if text_document.language_id != LANGUAGE_ID:
                continue

            diagnostics = validate_gherkin(ls, text_document)
            ls.publish_diagnostics(text_document.uri, diagnostics)  # type: ignore
    except:
        ls.logger.exception('failed to rebuild inventory', notify=True)


@server.command(COMMAND_RUN_DIAGNOSTICS)
def command_run_diagnostics(ls: GrizzlyLanguageServer, *args: Any) -> None:
    uri = '<unknown>'
    try:
        arg = args[0][0]
        uri = arg.get('uri', {}).get('external', None)

        text_document = ls.workspace.get_text_document(uri)

        diagnostics = validate_gherkin(ls, text_document)
        ls.publish_diagnostics(text_document.uri, diagnostics)  # type: ignore
    except Exception:
        ls.logger.exception(f'failed to run diagnostics on {uri}', notify=True)


@server.command(COMMAND_RENDER_GHERKIN)
def command_render_gherkin(ls: GrizzlyLanguageServer, *args: Any) -> Tuple[bool, Optional[str]]:
    options = cast(Dict[str, str], args[0][0])

    content = options.get('content', None)
    path = options.get('path', None)
    on_the_fly = options.get('on_the_fly', False)

    if content is None or path is None:
        content = 'no content to preview'
        ls.logger.error(content, notify=True)
        return False, content

    try:
        return True, render_gherkin(path, content)
    except Exception:
        if not on_the_fly:
            ls.logger.exception(f'failed to render {path}', notify=True)
            return False, f'Failed to render\n{ls.logger.get_current_exception()}'
        return False, None
