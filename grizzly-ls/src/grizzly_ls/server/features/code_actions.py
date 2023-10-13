from __future__ import annotations

import re

from typing import List, Optional, Union, TYPE_CHECKING
from pathlib import Path

from lsprotocol import types as lsp
from pygls.workspace import TextDocument

from grizzly_ls.constants import MARKER_NO_STEP_IMPL
from grizzly_ls.text import get_step_parts


if TYPE_CHECKING:
    from grizzly_ls.server import GrizzlyLanguageServer


def generate_quick_fixes(
    ls: GrizzlyLanguageServer,
    diagnostics: List[lsp.Diagnostic],
    text_document: TextDocument,
) -> Optional[List[Union[lsp.Command, lsp.CodeAction]]]:
    quick_fixes: List[Union[lsp.Command, lsp.CodeAction]] = []

    files = sorted(
        [
            file
            for file in ls.root_path.rglob('*.py')
            if file.name in ['environment.py', 'steps.py']
        ],
        reverse=True,
    )

    quick_fix_file: Optional[Path] = files[0] if len(files) > 0 else None

    step_impl_template = ls.client_settings.get('quick_fix', {}).get(
        'step_impl_template', None
    )

    for diagnostic in diagnostics:
        if (
            diagnostic.message.startswith(MARKER_NO_STEP_IMPL)
            and quick_fix_file is not None
            and step_impl_template is not None
        ):
            _, message_expression = diagnostic.message.split('\n', 1)
            keyword, expression = get_step_parts(message_expression)
            if keyword is None or expression is None:
                continue

            try:
                keyword_key = ls.get_language_key(keyword)

                variable_matches = list(
                    re.finditer(r'"([^"]*)"', expression or '', flags=re.MULTILINE)
                )

                if variable_matches:
                    pass

                new_text = '''
{step_impl_template}
def step_impl(context: Context) -> None:
raise NotImplementedError('no step implementation, yet')
'''.format(
                    step_impl_template=step_impl_template.format(
                        keyword=keyword_key, expression=expression
                    )
                )

                target_source = quick_fix_file.read_text().splitlines()
                position = lsp.Position(line=len(target_source), character=0)

                quick_fixes.append(
                    lsp.CodeAction(
                        title='Create step implementation',
                        kind=lsp.CodeActionKind.QuickFix,
                        edit=lsp.WorkspaceEdit(
                            changes={
                                str(quick_fix_file): [
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
                        disabled=lsp.CodeActionDisabledType(reason='not applicable'),
                    )
                )
            except ValueError:
                pass

    return quick_fixes if len(quick_fixes) > 0 else None
