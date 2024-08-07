import os
import subprocess
import logging
import re

from typing import Dict, List, Optional, Tuple, Set, Union, Iterable
from pathlib import Path

from jinja2.lexer import Token, TokenStream
from jinja2_simple_tags import StandaloneTag
from behave.parser import parse_feature
from pygls.server import LanguageServer
from lsprotocol import types as lsp


logger = logging.getLogger(__name__)


def run_command(
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> Tuple[int, List[str]]:
    logger.debug(f'executing command: {" ".join(command)}')
    output: List[str] = []

    if env is None:
        env = os.environ.copy()

    if cwd is None:
        cwd = os.getcwd()

    process = subprocess.Popen(
        command,
        env=env,
        cwd=cwd,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )

    try:
        while process.poll() is None:
            stdout = process.stdout
            if stdout is None:  # pragma: no cover
                break

            buffer = stdout.readline()
            if not buffer:
                break

            try:
                output.append(buffer.decode())
            except Exception:
                logger.exception(buffer)

        process.terminate()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        try:
            process.kill()
        except Exception:  # pragma: no cover
            pass

    process.wait()

    return process.returncode, output


class LogOutputChannelLogger:
    ls: LanguageServer
    logger: logging.Logger
    embedded: bool

    def __init__(self, ls: LanguageServer) -> None:
        self.ls = ls
        self.logger = logging.getLogger(ls.__class__.__name__)
        self.embedded = os.environ.get('GRIZZLY_RUN_EMBEDDED', 'false') == 'true'

    @classmethod
    def py2lsp_level(cls, level: int) -> lsp.MessageType:
        if level == logging.INFO:
            return lsp.MessageType.Info
        elif level == logging.ERROR:
            return lsp.MessageType.Error
        elif level == logging.WARNING:
            return lsp.MessageType.Warning
        elif level == logging.DEBUG:
            return lsp.MessageType.Debug

        return lsp.MessageType.Log

    def log(self, level: int, message: str) -> None:
        if not self.embedded:
            self.logger.log(level, message)
        else:
            self.ls.show_message_log(message, msg_type=self.py2lsp_level(level))  # type: ignore

    def info(self, message: str) -> None:
        self.log(logging.INFO, message)

    def error(self, message: str) -> None:
        self.log(logging.ERROR, message)

    def debug(self, message: str) -> None:
        self.log(logging.DEBUG, message)

    def warning(self, message: str) -> None:
        self.log(logging.WARNING, message)


class OnlyScenarioTag(StandaloneTag):
    tags = {'scenario'}
    logger: LogOutputChannelLogger

    def preprocess(self, source: str, name: Optional[str], filename: Optional[str] = None) -> str:
        self._source = source
        self.logger.debug(f'rendering {self.environment.feature_file.as_posix()}')

        # make sure all included scenarios has the same indentation
        for line in self._source.splitlines():
            match = re.match(r'^(\s+)\w.*$', line)
            if match:
                try:
                    _ = self.environment.indent
                except:
                    indentation = (len(line) - len(line.lstrip())) * 2
                    self.environment.extend(indent=indentation)
                    self.logger.debug(f'setting indentation to {indentation} spaces')
                break

        return super().preprocess(source, name, filename)

    def render(self, scenario: str, feature: str, **variables: str) -> str:
        feature_file = Path(feature)

        self.logger.debug(f'sub-rendering included {feature_file.as_posix()}')

        # check if relative to parent feature file
        if not feature_file.exists():
            feature_file = (self.environment.feature_file.parent / feature).resolve()

        feature_content = feature_file.read_text()
        # <!-- sub-render included scenario
        errors_unused: Set[str] = set()
        errors_undeclared: Set[str] = set()

        # tag has specified variables, so lets "render"
        if len(variables) > 0:
            for name, value in variables.items():
                variable_template = f'{{$ {name} $}}'
                if variable_template not in feature_content:
                    errors_unused.add(name)
                    continue

                feature_content = feature_content.replace(variable_template, value)

        # look for sub-variables that has not been rendered
        if '{$' in feature_content and '$}' in feature_content:
            matches = re.finditer(r'\{\$ ([^$]+) \$\}', feature_content, re.MULTILINE)

            for match in matches:
                errors_undeclared.add(match.group(1))

        if len(errors_undeclared) + len(errors_unused) > 0:
            scenario_identifier = f'{feature}#{scenario}'
            buffer_error: List[str] = []
            if len(errors_unused) > 0:
                errors_unused_message = "\n  ".join(errors_unused)
                buffer_error.append(f'the following variables has been declared in scenario tag but not used in {scenario_identifier}:\n  {errors_unused_message}')
                buffer_error.append('')

            if len(errors_undeclared) > 0:
                errors_undeclared_message = "\n  ".join(errors_undeclared)
                buffer_error.append(f'the following variables was used in {scenario_identifier} but was not declared in scenario tag:\n  {errors_undeclared_message}')
                buffer_error.append('')

            message = '\n'.join(buffer_error)
            raise ValueError(message)

        # check if we have nested `{% scenario .. %}` tags, and render
        if '{% scenario' in feature_content:
            original_feature_file = self.environment.feature_file
            self.environment.feature_file = feature_file

            template = self.environment.from_string(feature_content)
            feature_content = template.render()

            self.environment.feature_file = original_feature_file
        # // -->

        feature_lines = feature_content.splitlines()
        parsed_feature = parse_feature(feature_content, filename=feature_file.as_posix())

        if parsed_feature is None:
            raise ValueError(f'not a valid feature in {feature_file.as_posix()}')

        buffer_feature: List[str] = []

        for parsed_scenario in parsed_feature.scenarios:
            if parsed_scenario.name != scenario:
                continue

            buffer_scenario: List[str] = []

            scenario_line = feature_lines[parsed_scenario.line - 1]
            try:
                step_indent = self.environment.indent
            except:
                step_indent = (len(scenario_line) - len(scenario_line.lstrip())) * 2
                self.environment.extend(indent=step_indent)
                self.logger.debug(f'calculating indentation to {step_indent} spaces')

            for index, parsed_step in enumerate(parsed_scenario.steps):
                step_line = f'{parsed_step.keyword} {parsed_step.name}'

                # all lines except first, should have indentation based on how `Scenario:` had been indented
                if index > 0:
                    step_line = f'{" " * step_indent}{step_line}'

                buffer_scenario.append(step_line)

                extra_indent = int((step_indent / 2) + step_indent)

                # include step text if set
                if parsed_step.text is not None:
                    buffer_scenario.append(f'{" " * extra_indent}"""')
                    for text_line in parsed_step.text.splitlines():
                        buffer_scenario.append(f'{" " * (extra_indent)}{text_line}')
                    buffer_scenario.append(f'{" " * extra_indent}"""')

                # include step table if set
                if parsed_step.table is not None:
                    header_line = ' | '.join(parsed_step.table.headings)
                    buffer_scenario.append(f'{" " * extra_indent}| {header_line} |')
                    for row in parsed_step.table.rows:
                        row_line = ' | '.join(row.cells)
                        buffer_scenario.append(f'{" " * extra_indent}| {row_line} |')

            feature_scenario = '\n'.join(buffer_scenario)
            buffer_feature.append(feature_scenario)

        return '\n'.join(buffer_feature)

    def filter_stream(self, stream: TokenStream) -> Union[TokenStream, Iterable[Token]]:  # type: ignore[return]
        """Everything outside of `{% scenario ... %}` should be treated as "data", e.g. plain text.

        Overloaded from `StandaloneTag`, must match method signature, which is not `Generator`, even though we yield
        the result instead of returning.
        """
        in_scenario = False
        in_block_comment = False

        variable_begin_pos = -1
        variable_end_pos = 0
        block_begin_pos = -1
        block_end_pos = 0
        source_lines = self._source.splitlines()

        for token in stream:
            if token.type == 'block_begin' and stream.current.value in self.tags:
                in_scenario = True
                current_line = source_lines[token.lineno - 1].lstrip()
                in_block_comment = current_line.startswith('#')
                block_begin_pos = self._source.index(token.value, block_begin_pos + 1)

            if not in_scenario:
                token_value: Optional[str] = None

                if token.type == 'variable_end':
                    # Find variable end in the source
                    variable_end_pos = self._source.index(token.value, variable_begin_pos)
                    # Extract the variable definition substring and use as token value
                    token_value = self._source[variable_begin_pos : variable_end_pos + len(token.value)]
                elif token.type == 'variable_begin':
                    # Find variable start in the source
                    variable_begin_pos = self._source.index(token.value, variable_begin_pos + 1)
                    token_value = None
                else:
                    token_value = token.value

                if token_value is not None:
                    filtered_token = Token(token.lineno, 'data', token_value)
                else:
                    continue
            else:
                if token.type == 'block_end' and in_block_comment:
                    in_block_comment = False
                    block_end_pos = self._source.index(token.value, block_begin_pos)
                    token_value = self._source[block_begin_pos : block_end_pos + len(token.value)]
                    filtered_token = Token(token.lineno, 'data', token_value)
                elif in_block_comment:
                    continue
                else:
                    filtered_token = token

            yield filtered_token

            if in_scenario and token.type == 'block_end':
                in_scenario = False
