import logging
import platform

from os import environ
from os.path import pathsep
from typing import Any, Tuple, Dict, List
from pathlib import Path
from behave.matchers import ParseMatcher
from pip._internal.cli.main import main as pipmain
from venv import create as venv_create
from tempfile import gettempdir
from difflib import get_close_matches

from pygls.server import LanguageServer
from pygls.lsp.methods import (
    COMPLETION,
    INITIALIZE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_CLOSE,
)
from pygls.lsp.types import (
    CompletionParams,
    CompletionList,
    CompletionItem,
    CompletionItemKind,
    InitializeParams,
    DidOpenTextDocumentParams,
    DidCloseTextDocumentParams,
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

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)  # type: ignore

        @self.feature(INITIALIZE)
        def initialize(params: InitializeParams) -> None:
            assert params.root_path is not None, 'no root_path received from client'

            root_path = Path(params.root_path)
            project_name = root_path.stem

            virtual_environment = Path(gettempdir()) / f'grizzly-ls-{project_name}'

            self.logger.debug(f'looking for venv at {virtual_environment}')

            has_venv = virtual_environment.exists()

            if not has_venv:
                self.logger.debug(f'creating virtual environment: {virtual_environment}')
                venv_create(str(virtual_environment))

            if platform.system() == 'Windows':
                bin_dir = 'Scripts'
            else:
                bin_dir = 'bin'

            paths = [str(virtual_environment / bin_dir), environ.get('PATH', '')]
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
                pipmain(['install', '-r', str(requirements_file)])

            self._make_step_registry(root_path / 'features' / 'steps')
            total_steps = 0
            for steps in self.steps.values():
                total_steps += len(steps)
            self.show_message(f'found {total_steps} steps in grizzly project {project_name}')  # type: ignore

            self._make_keyword_registry()
            self.show_message(f'found {len(self.keywords)} keywords in behave')  # type: ignore

        @self.feature(TEXT_DOCUMENT_DID_OPEN)
        def text_document_did_open(params: DidOpenTextDocumentParams) -> None:
            """
            text_document=TextDocumentItem(
                uri='file:///workspaces/grizzly-vscode/tests/project/features/project.feature',
                language_id='grizzly-gherkin',
                version=1,
                text='Feature: Template feature file\n  Scenario: Template scenario\n    Given a user of type 'RestApi' with weight '1' load testing '$conf::template.host'\n'
            )
            """
            self.logger.debug(f'did_open: {params}')

        @self.feature(TEXT_DOCUMENT_DID_CLOSE)
        def text_document_did_close(params: DidCloseTextDocumentParams) -> None:
            """
            text_document=TextDocumentIdentifier(
                uri='file:///workspaces/grizzly-vscode/tests/project/features/project.feature'
            )
            """
            self.logger.debug(f'did_close: {params}')

        @self.feature(COMPLETION)
        def completions(params: CompletionParams) -> CompletionList:
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

            if keyword == 'And':  # And is an alias for Given, can only be used if preceeded by And or Given
                keyword = 'Given'

            if keyword is None or keyword not in self.keywords:
                keywords = self.keywords.copy()
                for keyword_once in self.keywords_once:
                    if f'{keyword_once}:' not in document.source:
                        keywords.append(keyword_once)

                items = list(
                    map(
                        lambda k: CompletionItem(
                            label=k,
                            kind=CompletionItemKind.Keyword,
                        ),
                        keywords,
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

    def _make_step_registry(self, step_path: Path) -> None:
        load_step_modules([str(step_path)])

        self.steps: Dict[str, List[str]] = {}
        registry_steps: Dict[str, List[ParseMatcher]] = registry.steps

        def get_pattern(step: ParseMatcher) -> str:
            return step.pattern

        for keyword, steps in registry_steps.items():
            self.steps.update({keyword: list(map(get_pattern, steps))})

        self.logger.info(self.steps)

    def _make_keyword_registry(self) -> None:
        self.keywords = ['Scenario', 'And']

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
