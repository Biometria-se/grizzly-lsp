import logging
import platform

from os import environ
from os.path import pathsep
from typing import Any, Tuple, Dict, List
from pathlib import Path
from pip._internal import main as pipmain
from venv import create as venv_create
from tempfile import gettempdir
from importlib import import_module

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
    InitializeParams,
    DidOpenTextDocumentParams,
    DidCloseTextDocumentParams,
)


class GrizzlyProject:
    name: str
    root_path: Path
    steps: Dict[str, List[Any]]

    def __init__(self, name: str, root_path: Path, steps: Dict[str, List[Any]]) -> None:
        self.name = name
        self.root_path = root_path
        self.steps = steps


class GrizzlyLanguageServer(LanguageServer):
    logger: logging.Logger = logging.getLogger(__name__)

    projects: Dict[str, GrizzlyProject]

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)  # type: ignore

        self.projects = {}

        @self.feature(INITIALIZE)
        def initialize(ls: LanguageServer, params: InitializeParams) -> None:
            self.logger.info(f'initialize got: {params}')

            assert params.root_path is not None, 'no root_path received from client'

            root_path = Path(params.root_path)
            project_name = root_path.stem

            virtual_environment = Path(gettempdir()) / f'grizzly-vscode-{project_name}'

            self.logger.info(f'looking for venv at {virtual_environment}')

            has_venv = virtual_environment.exists()

            if not has_venv:
                self.logger.info(f'creating virtual environment: {virtual_environment}')
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
                self.logger.info(f'installing {requirements_file}')
                pipmain(['install', '-r', str(requirements_file)])

            if project_name not in self.projects:
                behave_runner_util = import_module('behave.runner_util')
                behave_step_registry = import_module('behave.step_registry')

                behave_runner_util.load_step_modules([str(root_path / 'features' / 'steps')])

                project = GrizzlyProject(project_name, root_path, behave_step_registry.registry.steps)

                self.projects.update({project_name: project})

                from pprint import pformat

                self.logger.info(pformat(project.steps, indent=2))

                total_steps = 0
                for steps in project.steps.values():
                    total_steps += len(steps)

                ls.show_message_log(f'found {total_steps} steps in grizzly project {project_name}')  # type: ignore

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
            self.logger.info(f'completions got: {params}')
            return CompletionList(
                is_incomplete=False,
                item=[],
            )
