from __future__ import annotations

import sys
import re
import inspect

from typing import Optional, List, TYPE_CHECKING
from pathlib import Path
from urllib.parse import urlparse

from lsprotocol import types as lsp

from grizzly_ls.text import get_step_parts


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


def get_step_definition(ls: GrizzlyLanguageServer, params: lsp.DefinitionParams, current_line: str) -> Optional[lsp.LocationLink]:
    step_definition: Optional[lsp.LocationLink] = None

    keyword, expression = get_step_parts(current_line)

    if keyword is None or expression is None:
        return None

    expression = re.sub(r'"[^"]*"', '""', expression)
    for steps in ls.steps.values():
        for step in steps:
            if step.expression != expression:
                continue

            # support projects that wraps the behave step decorators
            step_func = getattr(step.func, '__wrapped__', step.func)

            if isinstance(step_func, staticmethod):
                step_func = step_func.__func__

            file_location = inspect.getfile(step_func)
            _, lineno = inspect.getsourcelines(step_func)

            range = lsp.Range(
                start=lsp.Position(line=lineno, character=0),
                end=lsp.Position(line=lineno, character=0),
            )
            step_definition = lsp.LocationLink(
                target_uri=Path(file_location).resolve().as_uri(),
                target_range=range,
                target_selection_range=range,
                origin_selection_range=lsp.Range(
                    start=lsp.Position(
                        line=params.position.line,
                        character=(len(current_line) - len(current_line.lstrip())),
                    ),
                    end=lsp.Position(
                        line=params.position.line,
                        character=len(current_line),
                    ),
                ),
            )

            # we have found what we are looking for
            break

    return step_definition


def get_file_url_definition(
    ls: GrizzlyLanguageServer,
    params: lsp.DefinitionParams,
    current_line: str,
) -> List[lsp.LocationLink]:
    text_document = ls.workspace.get_text_document(params.text_document.uri)
    document_directory = Path(text_document.path).parent
    definitions: List[lsp.LocationLink] = []
    matches = re.finditer(r'"([^"]*)"', current_line, re.MULTILINE)

    stripped_line = current_line.strip()
    is_expression = stripped_line[:2] == '{%' and stripped_line[-2:] == '%}'

    for variable_match in matches:
        variable_value = variable_match.group(1)

        if 'file://' in variable_value:
            file_match = re.search(r'.*(file:\/\/)([^\$]*)', variable_value)
            if not file_match:
                continue

            file_url = f'{file_match.group(1)}{file_match.group(2)}'

            if sys.platform == 'win32':  # pragma: no cover
                file_url = file_url.replace('\\', '/')
                file_url = file_url.replace('file:///', 'file://')

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
            if is_expression:
                ls.logger.debug(f'{variable_value=}')
                base_path = Path(text_document.path).parent
                if variable_value[:2] == './':  # relative path
                    payload_file = base_path / variable_value[2:]
                elif '/' not in variable_value:  # relative path
                    payload_file = base_path / variable_value
                else:  # absolute path
                    payload_file = Path(variable_value).resolve()
            else:
                payload_file = ls.root_path / 'features' / 'requests' / variable_value

            start_offset = 0
            end_offset = 0

        # just some text
        if not payload_file.exists():
            continue

        start = variable_match.start(1) + start_offset
        end = variable_match.end(1) + end_offset

        # don't add link definition if cursor is out side of range for that link
        if params.position.character >= start and params.position.character <= end:
            range = lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            )

            definitions.append(
                lsp.LocationLink(
                    target_uri=payload_file.as_uri(),
                    target_range=range,
                    target_selection_range=range,
                    origin_selection_range=lsp.Range(
                        start=lsp.Position(line=params.position.line, character=start),
                        end=lsp.Position(line=params.position.line, character=end),
                    ),
                )
            )

    return definitions
