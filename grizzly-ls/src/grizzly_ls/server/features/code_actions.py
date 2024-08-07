from __future__ import annotations

import re

from typing import List, Optional, Union, TYPE_CHECKING
from pathlib import Path
from difflib import get_close_matches

from lsprotocol import types as lsp
from behave.i18n import languages
from pygls.workspace import TextDocument
from random_word import RandomWords

from grizzly_ls.constants import (
    MARKER_NO_STEP_IMPL,
    MARKER_LANGUAGE,
    MARKER_LANG_NOT_VALID,
    MARKER_LANG_WRONG_LINE,
)
from grizzly_ls.text import get_step_parts, normalize_text


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


def quick_fix_no_step_impl(ls: GrizzlyLanguageServer, diagnostic: lsp.Diagnostic, text_document: TextDocument) -> Optional[lsp.CodeAction]:
    files = sorted(
        [file for file in ls.root_path.rglob('*.py') if file.name in ['environment.py', 'steps.py']],
        reverse=True,
    )

    quick_fix_file: Optional[Path] = files[0] if len(files) > 0 else None

    if quick_fix_file is None or not quick_fix_file.exists():
        return None

    step_impl_template = ls.client_settings.get('quick_fix', {}).get('step_impl_template', None)

    if step_impl_template is None:
        return None

    _, message_expression = diagnostic.message.split('\n', 1)
    keyword, expression = get_step_parts(message_expression)
    if keyword is None or expression is None:
        return None

    try:
        base_keyword = ls.get_base_keyword(diagnostic.range.start, text_document)

        keyword_key = ls.get_language_key(base_keyword)

        variable_matches = list(re.finditer(r'"([^"]*)"', expression or '', flags=re.MULTILINE))

        if variable_matches:
            generator = RandomWords()
            args: List[str] = []
            offset = 0
            for variable_match in variable_matches:
                variable_name = normalize_text(variable_match.group(1)).lower()
                if not variable_name.isidentifier():
                    variable_name = generator.get_random_word().lower()

                expression = f'{expression[0:variable_match.start() + offset]}"{{{variable_name}}}"{expression[variable_match.end() + offset:]}'
                offset += abs(len(variable_match.group(1)) - len(variable_name)) + 2  # we're also adding { and }
                args.append(f'{variable_name}: str')

            arguments = f', {", ".join(args)}'
        else:
            arguments = ''

        new_text = '''
{step_impl_template}
def step_impl(context: Context{arguments}) -> None:
    raise NotImplementedError('no step implementation')
'''.format(
            step_impl_template=step_impl_template.format(keyword=keyword_key, expression=expression),
            arguments=arguments,
        )

        target_source = quick_fix_file.read_text().splitlines()
        position = lsp.Position(line=len(target_source), character=0)

        return lsp.CodeAction(
            title='Create step implementation',
            kind=lsp.CodeActionKind.QuickFix,
            edit=lsp.WorkspaceEdit(
                changes={
                    quick_fix_file.as_uri(): [
                        lsp.TextEdit(
                            range=lsp.Range(
                                start=position,
                                end=position,
                            ),
                            new_text=new_text,
                        )
                    ]
                }
            ),
            diagnostics=[diagnostic],
            command=lsp.Command('Rebuild step inventory', 'grizzly.server.inventory.rebuild'),
        )
    except ValueError:
        return None


def _code_action_lang_not_valid(new_text: str, uri: str, range: lsp.Range) -> lsp.CodeAction:
    return lsp.CodeAction(
        title=f'Change language to "{new_text}"',
        kind=lsp.CodeActionKind.QuickFix,
        edit=lsp.WorkspaceEdit(
            changes={
                uri: [
                    lsp.TextEdit(range=range, new_text=new_text),
                ]
            }
        ),
    )


def quick_fix_lang_not_valid(text_document: TextDocument, diagnostic: lsp.Diagnostic) -> Optional[List[lsp.CodeAction]]:
    actions: List[lsp.CodeAction] = []
    _, language, _ = diagnostic.message.split('"', 2)

    # check if typed language is a long version
    for lang, localization in languages.items():
        if language.lower() in localization.get('name', ['___12341234__asdf'])[0].lower() or language.lower() in localization.get('native', ['___12341234_asdf'])[0].lower():
            actions.append(_code_action_lang_not_valid(lang, text_document.uri, diagnostic.range))

    # check if typed language has any close matches to available languages
    if len(actions) < 1:
        langs = list(languages.keys())

        possible_langs = get_close_matches(language, langs, len(langs), 0.5)

        for possible_lang in possible_langs:
            actions.append(_code_action_lang_not_valid(possible_lang, text_document.uri, diagnostic.range))

    # default to suggest to change to english
    if len(actions) < 1:
        actions.append(_code_action_lang_not_valid('en', text_document.uri, diagnostic.range))

    return actions


def quick_fix_lang_wrong_line(text_document: TextDocument, diagnostic: lsp.Diagnostic) -> Optional[lsp.CodeAction]:
    try:
        source_lines = text_document.source.splitlines()
        end_line = len(source_lines) - 1
        end_character = len(source_lines[-1]) - 1
        new_text = source_lines.pop(diagnostic.range.start.line)
        source = '\n'.join(source_lines)

        new_text = f'{new_text}\n{source}'

        range = lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=end_line, character=end_character),
        )

        return lsp.CodeAction(
            title=f'Move "{MARKER_LANGUAGE}" to first line',
            kind=lsp.CodeActionKind.QuickFix,
            edit=lsp.WorkspaceEdit(
                changes={
                    text_document.uri: [
                        lsp.TextEdit(
                            range=range,
                            new_text=new_text,
                        ),
                    ]
                }
            ),
        )
    except:
        return None


def generate_quick_fixes(
    ls: GrizzlyLanguageServer,
    text_document: TextDocument,
    diagnostics: List[lsp.Diagnostic],
) -> Optional[List[lsp.CodeAction]]:
    quick_fixes: List[lsp.CodeAction] = []

    for diagnostic in diagnostics:
        quick_fix: Optional[Union[lsp.CodeAction, List[lsp.CodeAction]]] = None
        if diagnostic.message.startswith(MARKER_NO_STEP_IMPL):
            quick_fix = quick_fix_no_step_impl(ls, diagnostic, text_document)
        elif diagnostic.message.endswith(MARKER_LANG_NOT_VALID):
            quick_fix = quick_fix_lang_not_valid(text_document, diagnostic)
        elif diagnostic.message.endswith(MARKER_LANG_WRONG_LINE):
            quick_fix = quick_fix_lang_wrong_line(text_document, diagnostic)

        if quick_fix is not None:
            if isinstance(quick_fix, list):
                quick_fixes.extend(quick_fix)
            else:
                quick_fixes.append(quick_fix)

    return quick_fixes if len(quick_fixes) > 0 else None
