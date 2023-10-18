from __future__ import annotations

import logging
import itertools
import re

from typing import Optional, Tuple, List, Set, Dict, TYPE_CHECKING
from tokenize import NAME, OP
from difflib import get_close_matches

from lsprotocol import types as lsp
from pygls.workspace import TextDocument
from behave.i18n import languages

from grizzly_ls.text import get_tokens
from grizzly_ls.constants import MARKER_LANGUAGE


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


logger = logging.getLogger(__name__)


def get_variable_name_trigger(trigger: str) -> Optional[Tuple[bool, Optional[str]]]:
    partial_variable_name: Optional[str] = None

    token_list = get_tokens(trigger)

    tokens_reversed = list(reversed(token_list))

    for index, token in enumerate(tokens_reversed):
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


def complete_metadata(
    line: str,
    position: lsp.Position,
) -> List[lsp.CompletionItem]:
    items: List[lsp.CompletionItem] = []
    if line.startswith(MARKER_LANGUAGE):
        _, expression = line.strip().split(MARKER_LANGUAGE, 1)
        expression = expression.strip()

        for lang, localization in languages.items():
            name = localization.get('name', ['___12341234_asdf'])[0]
            native = localization.get('native', ['___12341234_asdf'])[0]
            if (
                not (
                    expression.lower() in name.lower()
                    or expression.lower() in native.lower()
                    or expression.lower() in lang
                )
                and len(expression.strip()) > 0
            ):
                continue

            text_edit = lsp.TextEdit(
                range=lsp.Range(
                    start=lsp.Position(
                        line=position.line,
                        character=position.character - len(expression),
                    ),
                    end=position,
                ),
                new_text=lang,
            )

            items.append(
                lsp.CompletionItem(
                    label=lang,
                    kind=lsp.CompletionItemKind.Property,
                    text_edit=text_edit,
                )
            )
    else:
        text_edit = lsp.TextEdit(
            range=lsp.Range(
                start=lsp.Position(line=position.line, character=0),
                end=position,
            ),
            new_text=f'{MARKER_LANGUAGE} ',
        )
        items = [
            lsp.CompletionItem(
                label=MARKER_LANGUAGE,
                kind=lsp.CompletionItemKind.Property,
                text_edit=text_edit,
            )
        ]

    return items


def complete_keyword(
    ls: GrizzlyLanguageServer,
    keyword: Optional[str],
    position: lsp.Position,
    text_document: TextDocument,
) -> List[lsp.CompletionItem]:
    items: List[lsp.CompletionItem] = []
    if len(text_document.source.strip()) < 1:
        keywords = [*ls.localizations.get('feature', [])]
    else:
        scenario_keywords = [
            *ls.localizations.get('scenario', []),
            *ls.localizations.get('scenario_outline', []),
        ]

        if not any(
            [
                scenario_keyword in text_document.source
                for scenario_keyword in scenario_keywords
            ]
        ):
            keywords = scenario_keywords
        else:
            keywords = ls.keywords.copy()

        for keyword_once in ls.keywords_once:
            if f'{keyword_once}:' not in text_document.source:
                keywords.append(keyword_once)

        # check for partial matches
        if keyword is not None:
            keywords = [k for k in keywords if keyword.strip().lower() in k.lower()]

    for suggested_keyword in sorted(keywords):
        start = lsp.Position(
            line=position.line, character=position.character - len(keyword or '')
        )
        if suggested_keyword in ls.keywords_headers:
            suffix = ': '
        else:
            suffix = ' '

        text_edit = lsp.TextEdit(
            range=lsp.Range(
                start=start,
                end=position,
            ),
            new_text=f'{suggested_keyword}{suffix}',
        )

        items.append(
            lsp.CompletionItem(
                label=suggested_keyword,
                kind=lsp.CompletionItemKind.Keyword,
                deprecated=False,
                text_edit=text_edit,
            )
        )

    return items


def complete_variable_name(
    ls: GrizzlyLanguageServer,
    line: str,
    text_document: TextDocument,
    position: lsp.Position,
    *,
    partial: Optional[str] = None,
) -> List[lsp.CompletionItem]:
    items: List[lsp.CompletionItem] = []

    # find `Scenario:` before current position
    lines = text_document.source.splitlines()
    before_lines = reversed(lines[0 : position.line])

    for before_line in before_lines:
        if len(before_line.strip()) < 1:
            continue

        match = ls.variable_pattern.match(before_line)

        if match:
            variable_name = match.group(2) or match.group(3)

            if variable_name is None or (
                partial is not None and not variable_name.startswith(partial)
            ):
                continue

            text_edit: Optional[lsp.TextEdit] = None

            if partial is not None:
                prefix = ''
            else:
                prefix = '' if line[: position.character].endswith(' ') else ' '

            suffix = (
                '"'
                if not line.rstrip().endswith('"') and line.count('"') % 2 != 0
                else ''
            )
            affix = '' if line[position.character :].strip().startswith('}}') else '}}'
            affix_suffix = (
                ''
                if not line[position.character :].startswith('}}') and affix != '}}'
                else ' '
            )
            new_text = f'{prefix}{variable_name}{affix_suffix}{affix}{suffix}'

            start = lsp.Position(
                line=position.line,
                character=position.character - len(partial or ''),
            )
            text_edit = lsp.TextEdit(
                range=lsp.Range(
                    start=start,
                    end=lsp.Position(
                        line=position.line,
                        character=start.character + len(partial or ''),
                    ),
                ),
                new_text=new_text,
            )

            logger.debug(f'{line=}, {variable_name=}, {partial=}, {text_edit=}')

            items.append(
                lsp.CompletionItem(
                    label=variable_name,
                    kind=lsp.CompletionItemKind.Variable,
                    deprecated=False,
                    text_edit=text_edit,
                )
            )
        elif any(
            [
                scenario_keyword in before_line
                for scenario_keyword in ls.localizations.get('scenario', [])
            ]
        ):
            break

    return items


def complete_step(
    ls: GrizzlyLanguageServer,
    keyword: str,
    position: lsp.Position,
    expression: Optional[str],
) -> List[lsp.CompletionItem]:
    if keyword in ls.keywords_any:
        steps = list(
            set(
                [
                    step.expression
                    for keyword_steps in ls.steps.values()
                    for step in keyword_steps
                ]
            )
        )
    else:
        key = ls.get_language_key(keyword)
        steps = [
            step.expression for step in ls.steps.get(key, []) + ls.steps.get('step', [])
        ]

    matched_steps: List[lsp.CompletionItem] = []
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
    matched_steps_container: Dict[str, lsp.CompletionItem] = {}

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

        start = lsp.Position(line=position.line, character=position.character)
        preselect: bool = False
        if expression is not None and len(expression.strip()) > 0 and ' ' in expression:
            # only insert the part of the step that has not already been written, up until last space, since vscode
            # seems to insert text word wise
            new_text = matched_step.replace(expression, '')
            if not new_text.startswith(' ') and new_text.strip().count(' ') < 1:
                try:
                    _, new_text = matched_step.rsplit(' ', 1)
                except:  # pragma: no cover
                    pass
        else:
            new_text = matched_step

        # if matched step doesn't start what the user already had typed or we haven't removed
        # expression from matched step, we need to replace what already had been typed
        if (
            expression is not None
            and not new_text.startswith(expression)
            or new_text == matched_step
        ):
            character = start.character - len(str(expression))
            character = 0 if character < 0 else character
            start.character = character

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

        logger.debug(f'{expression=}, {new_text=}, {matched_step=}')

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

            insert_text_format = lsp.InsertTextFormat.Snippet
        else:
            insert_text_format = lsp.InsertTextFormat.PlainText

        text_edit = lsp.TextEdit(
            range=lsp.Range(start=start, end=position),
            new_text=new_text,
        )

        matched_steps_container.update(
            {
                matched_step: lsp.CompletionItem(
                    label=matched_step,
                    kind=lsp.CompletionItemKind.Function,
                    documentation=ls._find_help(f'{keyword} {matched_step}'),
                    deprecated=False,
                    preselect=preselect,
                    insert_text_format=insert_text_format,
                    text_edit=text_edit,
                )
            }
        )  # type: ignore

        matched_steps = list(matched_steps_container.values())

    return matched_steps
