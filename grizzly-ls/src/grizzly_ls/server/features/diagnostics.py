from __future__ import annotations

import re

from typing import Any, Dict, List, Optional, Tuple, Set, TYPE_CHECKING
from tokenize import tokenize, TokenError, NAME, ENCODING, STRING, OP
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
from contextlib import suppress

from pygls.workspace import TextDocument
from lsprotocol import types as lsp
from behave.parser import parse_feature, ParserError
from behave.i18n import languages
from behave.model import Feature
from ordered_set import OrderedSet

from grizzly_ls.constants import (
    MARKER_LANGUAGE,
    MARKER_NO_STEP_IMPL,
    MARKER_LANG_NOT_VALID,
    MARKER_LANG_WRONG_LINE,
)
from grizzly_ls.text import get_step_parts
from grizzly_ls.utils import ScenarioTag, MissingScenario


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


@dataclass
class ArgumentPosition:
    value: str
    start: int
    end: int


class GrizzlyDiagnostic(lsp.Diagnostic):
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, GrizzlyDiagnostic):
            return False

        if self.message != other.message or self.severity != other.severity or self.source != other.source:
            return False

        return (
            self.range.start.line == other.range.start.line
            and self.range.start.character == other.range.start.character
            and self.range.end.line == other.range.end.line
            and self.range.end.character == other.range.end.character
        )

    def __hash__(self) -> int:  # type: ignore[override]
        return hash((self.range.start.line, self.range.start.character, self.range.end.line, self.range.end.character, self.message, self.severity, self.source))


def _get_message_from_parse_error(error: ParserError, *, line_map: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    character = len(error.line_text) - len(error.line_text.strip()) if error.line_text is not None else 0
    message = str(error)

    # Remove static strings composed by ParserError.__str__
    message = re.sub(r'Failed to parse ("[^"]*"|\<string\>):', '', message).strip()

    # remove line_text from message
    if error.line_text is not None:
        message = message.replace(f': "{error.line_text}"', '').strip()

    match = re.search(r'.*at line ([0-9]+).*', message, flags=re.MULTILINE)
    if match:
        lineno = int(match.group(1))
        message = re.sub(rf',? at line {lineno}', '', message, flags=re.MULTILINE).strip()

        if error.line is None:
            error.line = lineno - 1

    if error.line_text is None:
        if '{%' not in message and '%}' not in message:
            match = re.search(r': "([^"]*)"', message, flags=re.MULTILINE)
            if match:
                error.line_text = match.group(1)

                message = re.sub(rf': "{error.line_text}"', '', message, flags=re.MULTILINE).strip()
        else:
            message, _ = message.split(':', 1)

    # map with un-stripped text, so we get correct ranges in the document
    if error.line_text is not None and line_map is not None:
        error.line_text = line_map.get(error.line_text, error.line_text)

    message = message.replace('REASON: ', '').strip()

    return character, message


def _remove_scenario_tags(source: str) -> str:
    # remove any expressions from source, since they messes up behave
    # feature parsing
    original_source = source
    if '{%' in original_source:
        buffer: List[str] = []
        for original_line in original_source.splitlines():
            stripped_line = original_line.lstrip()
            if stripped_line.startswith('{%'):
                continue
            buffer.append(original_line)

        source = '\n'.join(buffer)
    else:
        source = original_source

    return source


def validate_gherkin(ls: GrizzlyLanguageServer, text_document: TextDocument) -> List[lsp.Diagnostic]:
    diagnostics: OrderedSet[GrizzlyDiagnostic] = OrderedSet(set())
    line_map: Dict[str, str] = {}
    included_feature_files: Dict[str, Feature] = {}

    ignoring: bool = False
    language: str = 'en'
    zero_line_length = 0

    lines = text_document.source.splitlines()

    if text_document.source.count('"""') % 2 != 0:
        for lineno, line in enumerate(reversed(lines)):
            stripped_line = line.strip()
            if not stripped_line.startswith('"""'):
                continue

            position = len(line) - len(stripped_line)

            diagnostics.add(
                GrizzlyDiagnostic(
                    range=lsp.Range(
                        start=lsp.Position(line=len(lines) - lineno - 1, character=position),
                        end=lsp.Position(line=len(lines) - lineno - 1, character=len(line)),
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
        if len(stripped_line) < 1 or (stripped_line[0] == '#' and not stripped_line.startswith(MARKER_LANGUAGE)) or (stripped_line[0] == '|' and stripped_line[-1] == '|'):
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
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(line=lineno, character=marker_position),
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
                diagnostics.add(
                    GrizzlyDiagnostic(
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

        # handle jinja2 expressions
        if stripped_line[:2] == '{%' and stripped_line[-2:] == '%}':
            # only tokenize the actual jinja2 expression, not the markers
            try:
                tokens = list(tokenize(BytesIO(stripped_line[2:-2].strip().encode()).readline))
            except TokenError:
                continue

            if tokens[0].type == ENCODING:
                tokens.pop(0)

            # ignore any expression that isn't the "scenario" tag
            if not (tokens[0].type == NAME and tokens[0].string == 'scenario'):
                continue

            arg_scenario: Optional[ArgumentPosition] = None
            arg_feature: Optional[ArgumentPosition] = None
            arg_variables: List[Tuple[ArgumentPosition, ArgumentPosition]] = []

            peek = 0

            # check for scenario and feature arguments, can be both positional and named
            for index, token in enumerate(tokens[1:], start=1):
                if peek != 0 and index < peek + 1:
                    continue
                else:
                    peek = 0

                # scenario
                if arg_scenario is None:
                    if token.type == STRING:
                        value = token.string.strip('"\'')
                        arg_scenario = ArgumentPosition(value, start=token.start[1] + 2, end=token.end[1])
                    continue

                # feature
                if arg_feature is None:
                    if token.type == STRING:
                        value = token.string.strip('"\'')
                        arg_feature = ArgumentPosition(value, start=token.start[1] + 2, end=token.end[1])
                    continue

                with suppress(IndexError):
                    next_tokens = list(map(lambda t: t.type, tokens[index : index + 3]))
                    if next_tokens != [NAME, OP, STRING] and next_tokens != [NAME, OP, NAME]:
                        continue

                    peek = index + 2
                    value_token = tokens[peek]

                    variable_name = token.string
                    variable_value = value_token.string.strip('"\'')
                    offset = len(line) - len(stripped_line) + 3
                    arg_variables.append(
                        (
                            ArgumentPosition(variable_name, start=token.start[1] + offset, end=token.end[1] + offset),
                            ArgumentPosition(variable_value, start=value_token.start[1] + offset, end=value_token.end[1] + offset),
                        )
                    )

            # make sure arguments was found
            if arg_scenario is None:
                diagnostics.add(
                    GrizzlyDiagnostic(
                        range=lsp.Range(
                            start=lsp.Position(line=lineno, character=position),
                            end=lsp.Position(line=lineno, character=len(line)),
                        ),
                        message='Scenario tag is invalid, could not find scenario argument',
                        severity=lsp.DiagnosticSeverity.Error,
                        source=ls.__class__.__name__,
                    )
                )

            if arg_feature is None:
                diagnostics.add(
                    GrizzlyDiagnostic(
                        range=lsp.Range(
                            start=lsp.Position(line=lineno, character=position),
                            end=lsp.Position(line=lineno, character=len(line)),
                        ),
                        message='Scenario tag is invalid, could not find feature argument',
                        severity=lsp.DiagnosticSeverity.Error,
                        source=ls.__class__.__name__,
                    )
                )

            # if they were not found, no more validation for this line
            if arg_scenario is None or arg_feature is None:
                continue

            # make sure that the specified scenario exists in the specified feature file
            if arg_feature.value != '':
                base_path = Path(text_document.path).parent
                feature_path = Path(arg_feature.value)
                if feature_path.is_absolute():
                    feature_file = feature_path.resolve()
                else:
                    feature_file = (base_path / feature_path).resolve()

                if not feature_file.exists():
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno,
                                    character=arg_feature.start + position + 2,
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=arg_feature.end + position + 2,
                                ),
                            ),
                            message=f'Included feature file "{arg_feature.value}" does not exist',
                            severity=lsp.DiagnosticSeverity.Error,
                            source=ls.__class__.__name__,
                        )
                    )
                    continue

                try:
                    source = _remove_scenario_tags(feature_file.read_text(encoding='utf-8'))
                    feature = parse_feature(
                        source,
                        language=None,
                        filename=feature_file.as_posix(),
                    )

                    # it was possible to parse the feature file, but it didn't contain any scenarios
                    if feature is None:
                        diagnostics.add(
                            GrizzlyDiagnostic(
                                range=lsp.Range(
                                    start=lsp.Position(
                                        line=lineno,
                                        character=arg_feature.start + position + 2,
                                    ),
                                    end=lsp.Position(
                                        line=lineno,
                                        character=arg_feature.end + position + 2,
                                    ),
                                ),
                                message=f'Included feature file "{arg_feature.value}" does not have any scenarios',
                                severity=lsp.DiagnosticSeverity.Error,
                                source=ls.__class__.__name__,
                            )
                        )
                        continue

                    source = ScenarioTag.get_scenario_text(arg_scenario.value, feature_file)

                    # check if declared variables is used
                    declared_variables: Set[str] = set()
                    for arg_variable_name, arg_variable_value in arg_variables:
                        variable_template = f'\\{{\\$ {arg_variable_name.value} \\$\\}}'
                        matches = re.finditer(rf'^\s?.*{variable_template}.*$', source, re.MULTILINE)
                        found_variable = False
                        declared_variables.add(arg_variable_name.value)

                        for match in matches:
                            if match.group(0).strip()[0] == '#':
                                continue

                            found_variable = True

                        if not found_variable:
                            ls.logger.debug(f'{arg_variable_name=}, {arg_variable_value=}, {arg_variable_name.start=}, {arg_variable_value.end=}')
                            diagnostics.add(
                                GrizzlyDiagnostic(
                                    range=lsp.Range(
                                        start=lsp.Position(line=lineno, character=arg_variable_name.start),
                                        end=lsp.Position(line=lineno, character=arg_variable_value.end),
                                    ),
                                    message=f'Declared variable "{arg_variable_name.value}" is not used in included scenario steps',
                                    severity=lsp.DiagnosticSeverity.Error,
                                    source=ls.__class__.__name__,
                                )
                            )

                    # check if variables used has been declared
                    matches = re.finditer(r'^\s?.*\{\$ ([^\$]+) \$\}.*$', source, re.MULTILINE)
                    for match in matches:
                        variable_name = match.group(1)
                        variable_template = f'{{$ {variable_name} $}}'
                        if variable_name not in declared_variables:
                            start, end = match.span(0)
                            start = len(line) - len(stripped_line)
                            end = len(line)

                            diagnostics.add(
                                GrizzlyDiagnostic(
                                    range=lsp.Range(
                                        start=lsp.Position(line=lineno, character=start),
                                        end=lsp.Position(line=lineno, character=end),
                                    ),
                                    message=f'Scenario tag is missing variable "{variable_name}"',
                                    severity=lsp.DiagnosticSeverity.Warning,
                                    source=ls.__class__.__name__,
                                )
                            )
                    included_feature_files.update({arg_feature.value: feature})
                except ParserError as pe:
                    character, message = _get_message_from_parse_error(pe)
                    character = character or (len(line) - len(stripped_line))

                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(line=pe.line or 0, character=character),
                                end=lsp.Position(
                                    line=pe.line or 0,
                                    character=len(pe.line_text) - 1 if pe.line_text is not None else len(line),
                                ),
                            ),
                            message=message,
                            severity=lsp.DiagnosticSeverity.Information,
                            source=ls.__class__.__name__,
                        )
                    )

                    continue
                except MissingScenario as mse:
                    mse.feature = arg_feature.value  # we want the path that was set in the tag

                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.start + position + 2,
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.end + position + 2,
                                ),
                            ),
                            message=str(mse),
                            severity=lsp.DiagnosticSeverity.Error,
                            source=ls.__class__.__name__,
                        )
                    )
                    continue

            if arg_feature.value == '' or arg_scenario.value == '':
                if arg_feature.value == '':
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno,
                                    character=arg_feature.start + position + 2,
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=arg_feature.end + position + 2,
                                ),
                            ),
                            message='Feature argument is empty',
                            severity=lsp.DiagnosticSeverity.Warning,
                            source=ls.__class__.__name__,
                        )
                    )

                if arg_scenario.value == '':
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.start + position + 2,
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.end + position + 2,
                                ),
                            ),
                            message='Scenario argument is empty',
                            severity=lsp.DiagnosticSeverity.Warning,
                            source=ls.__class__.__name__,
                        )
                    )

                continue

            feature = included_feature_files[arg_feature.value]

            try:
                scenario = next(iter([scenario for scenario in feature.scenarios if scenario.name == arg_scenario.value]))

                if len(scenario.steps) < 1:
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.start + position + 2,
                                ),
                                end=lsp.Position(
                                    line=lineno,
                                    character=arg_scenario.end + position + 2,
                                ),
                            ),
                            message=f'Scenario "{arg_scenario.value}" in "{arg_feature.value}" does not have any steps',
                            severity=lsp.DiagnosticSeverity.Error,
                            source=ls.__class__.__name__,
                        )
                    )
            except StopIteration:
                continue
        else:
            # check if keywords are valid in the specified language
            keyword, expression = get_step_parts(stripped_line)
            lang_key: Optional[str] = None
            if keyword is not None:
                start_position = lsp.Position(line=lineno, character=position)
                keyword = keyword.rstrip(' :')
                base_keyword = ls.get_base_keyword(start_position, text_document)

                try:
                    lang_key = ls.get_language_key(base_keyword)
                except ValueError:
                    name = ls.localizations.get('name', ['unknown'])[0]

                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=start_position,
                                end=lsp.Position(line=lineno, character=position + len(keyword)),
                            ),
                            message=f'"{keyword}" is not a valid keyword in {name}',
                            severity=lsp.DiagnosticSeverity.Error,
                            source=ls.__class__.__name__,
                        )
                    )

            # check if step expression exists
            if lang_key is not None and expression is not None and keyword not in ls.keywords_headers:
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
                    diagnostics.add(
                        GrizzlyDiagnostic(
                            range=lsp.Range(
                                start=lsp.Position(line=lineno, character=len(line) - len(expression)),
                                end=lsp.Position(line=lineno, character=len(line)),
                            ),
                            message=f'{MARKER_NO_STEP_IMPL}\n{stripped_line}',
                            severity=lsp.DiagnosticSeverity.Warning,
                            source=ls.__class__.__name__,
                        )
                    )

    # make sure behave can parse it
    try:
        # remove any expressions from source, since they messes up behave
        # feature parsing
        source = _remove_scenario_tags(text_document.source)

        parse_feature(source, language=language, filename=text_document.filename)
    except ParserError as pe:
        character, message = _get_message_from_parse_error(pe, line_map=line_map)
        diagnostics.add(
            GrizzlyDiagnostic(
                range=lsp.Range(
                    start=lsp.Position(line=pe.line or 0, character=character),
                    end=lsp.Position(
                        line=pe.line or 0,
                        character=len(pe.line_text) - 1 if pe.line_text is not None else zero_line_length,
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
    line_map.clear()
    included_feature_files.clear()

    return list(diagnostics)
