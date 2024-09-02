from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Dict
from argparse import Namespace as Arguments
from pathlib import Path

from pygls.workspace import TextDocument
from lsprotocol.types import Diagnostic, DiagnosticSeverity
from colorama import init, Fore

from grizzly_ls.server.features.diagnostics import validate_gherkin
from grizzly_ls.server.inventory import compile_inventory
from grizzly_ls.text import find_language


if TYPE_CHECKING:  # pragma: no cover
    from grizzly_ls.server import GrizzlyLanguageServer


def _get_severity_color(severity: Optional[DiagnosticSeverity]) -> str:
    if severity == DiagnosticSeverity.Error:
        return Fore.RED
    elif severity == DiagnosticSeverity.Information:
        return Fore.BLUE
    elif severity == DiagnosticSeverity.Warning:
        return Fore.YELLOW
    elif severity == DiagnosticSeverity.Hint:
        return Fore.CYAN

    return Fore.RESET


def diagnostic_to_text(filename: str, diagnostic: Diagnostic, max_length: int) -> str:
    color = _get_severity_color(diagnostic.severity)
    severity = diagnostic.severity.name if diagnostic.severity is not None else 'unknown'
    message = ': '.join(diagnostic.message.split('\n'))

    message_file = f'{filename}:{diagnostic.range.start.line + 1}:{diagnostic.range.start.character + 1}'
    message_severity = f'{color}{severity.lower()}{Fore.RESET}'

    # take line number into consideration, max 9999:9999
    max_length += 9

    # color and reset codes makes the string 10 bytes longer than the actual text length -+
    #                                                                                     |
    #                                                        v----------------------------+
    return f'{message_file:<{max_length}} {message_severity:<17} {message}'


def cli(ls: GrizzlyLanguageServer, args: Arguments) -> int:
    files: List[Path]

    # init colorama for ansi colors
    init()

    # init language server
    ls.root_path = Path.cwd()
    ls.logger.logger.handlers = []
    ls.logger.logger.propagate = False
    compile_inventory(ls, standalone=True)

    if args.files == ['.']:
        files = list(Path.cwd().rglob('**/*.feature'))
    else:
        files = []
        paths = [Path(file) for file in args.files]

        for path in paths:
            file = Path(path)

            if file.is_dir():
                files.extend(list(file.rglob('**/*.feature')))
            else:
                files.append(file)

    rc: int = 0
    grouped_diagnostics: Dict[str, List[Diagnostic]] = {}
    max_length = 0

    for file in files:
        text_document = TextDocument(file.resolve().as_uri())
        ls.language = find_language(text_document.source)
        diagnostics = validate_gherkin(ls, text_document)

        if len(diagnostics) < 1:
            continue

        file = Path(text_document.uri.replace('file://', ''))
        filename = file.as_posix().replace(Path.cwd().as_posix(), '').lstrip('/\\')
        max_length = max(max_length, len(filename))

        grouped_diagnostics.update({filename: diagnostics})

    if len(grouped_diagnostics) > 0:
        rc = 1

    for filename, diagnostics in grouped_diagnostics.items():
        print('\n'.join(diagnostic_to_text(filename, diagnostic, max_length) for diagnostic in diagnostics))

    return rc
