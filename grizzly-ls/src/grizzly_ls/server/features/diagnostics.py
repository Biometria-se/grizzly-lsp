from __future__ import annotations

import re

from typing import Dict, List, Optional, TYPE_CHECKING

from pygls.workspace import TextDocument
from lsprotocol import types as lsp
from behave.parser import parse_feature, ParserError
from behave.i18n import languages

from grizzly_ls.constants import (
    MARKER_LANGUAGE,
    MARKER_NO_STEP_IMPL,
    MARKER_LANG_NOT_VALID,
    MARKER_LANG_WRONG_LINE,
)
from grizzly_ls.text import get_step_parts


if TYPE_CHECKING:
    from grizzly_ls.server import GrizzlyLanguageServer


def validate_gherkin(
    ls: GrizzlyLanguageServer, text_document: TextDocument
) -> List[lsp.Diagnostic]:
    diagnostics: List[lsp.Diagnostic] = []
    line_map: Dict[str, str] = {}

    ignoring: bool = False
    language: str = 'en'
    zero_line_length = 0

    ls.logger.debug(f'diagnostics for {text_document.uri}')

    lines = text_document.source.splitlines()

    if text_document.source.count('"""') % 2 != 0:
        for lineno, line in enumerate(reversed(lines)):
            stripped_line = line.strip()
            if not stripped_line.startswith('"""'):
                continue

            position = len(line) - len(stripped_line)

            diagnostics.append(
                lsp.Diagnostic(
                    range=lsp.Range(
                        start=lsp.Position(
                            line=len(lines) - lineno - 1, character=position
                        ),
                        end=lsp.Position(
                            line=len(lines) - lineno - 1, character=len(line)
                        ),
                    ),
                    message='Freetext marker is not closed',
                    severity=lsp.DiagnosticSeverity.Error,
                    source=ls.__class__.__name__,
                )
            )

            break

    for lineno, line in enumerate(lines):
        if lineno == 0:
            zero_line_length = len(line)

        stripped_line = line.strip()

        # ignore lines that are plain comments, or tables
        if (
            len(stripped_line) < 1
            or (
                stripped_line[0] == '#'
                and not stripped_line.startswith(MARKER_LANGUAGE)
            )
            or (stripped_line[0] == '|' and stripped_line[-1] == '|')
        ):
            continue

        # ignore any lines that comes between free text, or empty lines, or lines that could be a table
        if stripped_line[:3] == '"""':
            ignoring = not ignoring
            continue

        if ignoring:
            continue

        position = len(line) - len(stripped_line)
        line_map.update({stripped_line: line})

        # validate language
        if stripped_line.startswith(MARKER_LANGUAGE):
            try:
                marker, language = line.split(': ', 1)
                # does not exist
                if len(language.strip()) > 0 and language.strip() not in languages:
                    marker_position = len(marker) + 2
                    diagnostics.append(
                        lsp.Diagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno, character=marker_position
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=marker_position + len(language),
                                ),
                            ),
                            message=f'"{language}" {MARKER_LANG_NOT_VALID}',
                            severity=lsp.DiagnosticSeverity.Error,
                            source=ls.__class__.__name__,
                        )
                    )
            except ValueError:  # not finished typing
                pass

            # wrong line
            if lineno != 0:
                diagnostics.append(
                    lsp.Diagnostic(
                        range=lsp.Range(
                            start=lsp.Position(line=lineno, character=position),
                            end=lsp.Position(line=lineno, character=len(line)),
                        ),
                        message=f'"{MARKER_LANGUAGE}" {MARKER_LANG_WRONG_LINE}',
                        severity=lsp.DiagnosticSeverity.Warning,
                        source=ls.__class__.__name__,
                    )
                )

            # nothing more to check on this line...
            continue

        keyword, expression = get_step_parts(stripped_line)

        # check if keywords are valid in the specified language
        lang_key: Optional[str] = None
        if keyword is not None:
            if keyword.endswith(':'):
                keyword = keyword[:-1]

            try:
                lang_key = ls.get_language_key(keyword)
            except ValueError:
                name = ls.localizations.get('name', ['unknown'])[0]

                diagnostics.append(
                    lsp.Diagnostic(
                        range=lsp.Range(
                            start=lsp.Position(line=lineno, character=position),
                            end=lsp.Position(
                                line=lineno, character=position + len(keyword)
                            ),
                        ),
                        message=f'"{keyword}" is not a valid keyword in {name}',
                        severity=lsp.DiagnosticSeverity.Error,
                        source=ls.__class__.__name__,
                    )
                )

        # check if step expression exists
        if (
            lang_key is not None
            and expression is not None
            and keyword not in ls.keywords_headers
        ):
            found_step = False
            expression_shell = re.sub(r'"[^"]*"', '""', expression)

            for steps in ls.steps.values():
                for step in steps:
                    # some step expressions might have enum values pre-filled,
                    # clean them out first
                    step_expression = re.sub(r'"[^"]*"', '""', step.expression)

                    if step_expression == expression_shell:
                        found_step = True
                        break

            if not found_step:
                diagnostics.append(
                    lsp.Diagnostic(
                        range=lsp.Range(
                            start=lsp.Position(
                                line=lineno, character=len(line) - len(expression)
                            ),
                            end=lsp.Position(line=lineno, character=len(line)),
                        ),
                        message=f'{MARKER_NO_STEP_IMPL}\n{stripped_line}',
                        severity=lsp.DiagnosticSeverity.Warning,
                        source=ls.__class__.__name__,
                    )
                )

    # make sure behave can parse it
    try:
        parse_feature(
            text_document.source, language=language, filename=text_document.filename
        )
    except ParserError as pe:
        character = (
            len(pe.line_text) - len(pe.line_text.strip())
            if pe.line_text is not None
            else 0
        )
        message = str(pe)

        # Remove static strings composed by ParserError.__str__
        message = re.sub(r'Failed to parse ("[^"]*"|\<string\>):', '', message).strip()

        # remove line_text from message
        if pe.line_text is not None:
            message = message.replace(f': "{pe.line_text}"', '').strip()

        match = re.search(r'.*at line ([0-9]+).*', message, flags=re.MULTILINE)
        if match:
            lineno = int(match.group(1))
            message = re.sub(
                rf',? at line {lineno}', '', message, flags=re.MULTILINE
            ).strip()

            if pe.line is None:
                pe.line = lineno - 1

        if pe.line_text is None:
            match = re.search(r': "([^"]*)"', message, flags=re.MULTILINE)
            if match:
                pe.line_text = match.group(1)

                message = re.sub(
                    rf': "{pe.line_text}"', '', message, flags=re.MULTILINE
                ).strip()

        # map with un-stripped text, so we get correct ranges in the document
        if pe.line_text is not None:
            pe.line_text = line_map.get(pe.line_text, pe.line_text)

        message = message.replace('REASON: ', '').strip()

        diagnostics.append(
            lsp.Diagnostic(
                range=lsp.Range(
                    start=lsp.Position(line=pe.line or 0, character=character),
                    end=lsp.Position(
                        line=pe.line or 0,
                        character=len(pe.line_text) - 1
                        if pe.line_text is not None
                        else zero_line_length,
                    ),
                ),
                message=message,
                severity=lsp.DiagnosticSeverity.Error,
                source=ls.__class__.__name__,
            )
        )
    except KeyError:
        pass

    # clean up
    line_map = {}

    return diagnostics
