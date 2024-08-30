import os
import subprocess
import logging
import re
import sys
import traceback

from typing import Dict, List, Optional, Tuple, Union, Iterable, Set
from pathlib import Path
from contextlib import suppress
from textwrap import dedent

from jinja2.lexer import Token, TokenStream
from jinja2_simple_tags import StandaloneTag
from behave.parser import parse_feature
from behave.model import Scenario
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

    def get_current_exception(self) -> Optional[str]:
        _, _, trace = sys.exc_info()

        if trace is None:
            return trace

        return f'Stack trace:\n{"".join(traceback.format_tb(trace))}'

    def log(self, level: int, message: str, *, exc_info: bool, notify: bool) -> None:
        msg_type = self.py2lsp_level(level)
        if not self.embedded:
            self.logger.log(level, message, exc_info=exc_info)
        else:
            if exc_info:
                message = f'{message}\n{self.get_current_exception()}'
            self.ls.show_message_log(message, msg_type=msg_type)  # type: ignore

        if notify:
            self.ls.show_message(message, msg_type=msg_type)  # type: ignore

    def info(self, message: str, *, notify: bool = False) -> None:
        self.log(logging.INFO, message, exc_info=False, notify=notify)

    def error(self, message: str, *, notify: bool = False) -> None:
        self.log(logging.ERROR, message, exc_info=False, notify=notify)

    def debug(self, message: str, *, notify: bool = False) -> None:
        self.log(logging.DEBUG, message, exc_info=False, notify=notify)

    def warning(self, message: str, *, notify: bool = False) -> None:
        self.log(logging.WARNING, message, exc_info=False, notify=notify)

    def exception(self, message: str, *, notify: bool = False) -> None:
        self.log(logging.ERROR, message, exc_info=True, notify=notify)


class ScenarioTag(StandaloneTag):
    tags = {'scenario'}

    def preprocess(self, source: str, name: Optional[str], filename: Optional[str] = None) -> str:
        self._source = source

        return super().preprocess(source, name, filename)

    def render(self, scenario: str, feature: str, **variables: str) -> str:
        feature_file = Path(feature)

        # check if relative to parent feature file
        if not feature_file.exists():
            feature_file = (self.environment.feature_file.parent / feature).resolve()

        feature_content = feature_file.read_text()
        # <!-- sub-render included scenario
        errors_unused: Set[str] = set()
        errors_undeclared: Set[str] = set()

        # tag has specified variables, so lets "render"
        for name, value in variables.items():
            variable_template = f'{{$ {name} $}}'
            if variable_template not in feature_content:
                errors_unused.add(name)
                continue

            feature_content = feature_content.replace(variable_template, str(value))

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
        if '{%' in feature_content and '%}' in feature_content:
            environment = self.environment.overlay()
            environment.extend(feature_file=feature_file)
            template = environment.from_string(feature_content)
            feature_content = template.render()
        # // -->

        source_lines = feature_content.splitlines()

        parsed_feature = parse_feature(feature_content, filename=feature_file.as_posix())
        if parsed_feature is None:
            raise ValueError(f'unable to parse {feature_file.as_posix()}')

        parsed_scenarios = parsed_feature.scenarios
        parsed_scenario: Optional[Scenario] = None
        scenario_index: int = -1

        for scenario_index, parsed_scenario in enumerate(parsed_scenarios):
            if parsed_scenario.name == scenario:
                break

        if parsed_scenario is None:
            raise ValueError(f'could not find {scenario} in {feature_file.as_posix()}')

        # check if there are scenarios after our scenario in the source
        next_scenario: Optional[Scenario] = None
        with suppress(IndexError):
            next_scenario = parsed_scenarios[scenario_index + 1]

        if next_scenario is None:  # last scenario, take everything until the end
            target_lines = source_lines[parsed_scenario.line :]
        else:  # take everything up until where the next scenario starts
            target_lines = source_lines[parsed_scenario.line : next_scenario.line - 1]
            if target_lines[-1] == '':  # if last line is an empty line, lets remove it
                target_lines.pop()

        # first line can have incorrect indentation
        target_lines[0] = dedent(target_lines[0])

        return '\n'.join(target_lines)

    def filter_stream(self, stream: TokenStream) -> Union[TokenStream, Iterable[Token]]:  # type: ignore[return]
        """Everything outside of `{% scenario ... %}` (and `{% if ... %}...{% endif %}`) should be treated as "data", e.g. plain text.

        Overloaded from `StandaloneTag`, must match method signature, which is not `Generator`, even though we yield
        the result instead of returning.
        """
        in_scenario = False
        in_block_comment = False
        in_condition = False

        variable_begin_pos = -1
        variable_end_pos = 0
        block_begin_pos = -1
        block_end_pos = 0
        source_lines = self._source.splitlines()

        for token in stream:
            if token.type == 'block_begin':
                if stream.current.value in self.tags:  # {% scenario ... %}
                    in_scenario = True
                    current_line = source_lines[token.lineno - 1].lstrip()
                    in_block_comment = current_line.startswith('#')
                    block_begin_pos = self._source.index(token.value, block_begin_pos + 1)
                elif stream.current.value in ['if', 'endif']:  # {% if <condition %}, {% endif %}
                    in_condition = True

            if in_scenario:
                if token.type == 'block_end' and in_block_comment:
                    in_block_comment = False
                    block_end_pos = self._source.index(token.value, block_begin_pos)
                    token_value = self._source[block_begin_pos : block_end_pos + len(token.value)]
                    filtered_token = Token(token.lineno, 'data', token_value)
                elif in_block_comment:
                    continue
                else:
                    filtered_token = token
            elif in_condition:
                filtered_token = token
            else:
                if token.type == 'variable_end':
                    # Find variable end in the source
                    variable_end_pos = self._source.index(token.value, variable_begin_pos)
                    # Extract the variable definition substring and use as token value
                    token_value = self._source[variable_begin_pos : variable_end_pos + len(token.value)]
                elif token.type == 'variable_begin':
                    # Find variable start in the source
                    variable_begin_pos = self._source.index(token.value, variable_begin_pos + 1)
                    continue
                else:
                    token_value = token.value

                filtered_token = Token(token.lineno, 'data', token_value)

            yield filtered_token

            if token.type == 'block_end':
                if in_scenario:
                    in_scenario = False

                if stream.current.value == 'endif':  # {% endif %}
                    in_condition = False
