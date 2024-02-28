from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional
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


def diagnostic_to_text(filename: str, diagnostic: Diagnostic) -> str:
    color = _get_severity_color(diagnostic.severity)
    severity = diagnostic.severity.name if diagnostic.severity is not None else 'UNKNOWN'
    message = ': '.join(diagnostic.message.split('\n'))

    return '\t'.join(
        [
            f'{filename}:{diagnostic.range.start.line+1}:{diagnostic.range.start.character+1}',
            f'{color}{severity.lower()}{Fore.RESET}',
            message,
        ]
    )


def cli(ls: GrizzlyLanguageServer, args: Arguments) -> int:
    files: List[Path]

    # init colorama for ansi colors
    init()

    # init language server
    ls.root_path = Path.cwd()
    ls.logger.handlers = []
    ls.logger.propagate = False
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
    for file in files:
        text_document = TextDocument(file.resolve().as_uri())
        ls.language = find_language(text_document.source)
        diagnostics = validate_gherkin(ls, text_document)

        if len(diagnostics) < 1:
            continue

        rc = 1

        filename = file.as_posix().replace(Path.cwd().as_posix(), '').lstrip('/\\')

        for diagnostic in diagnostics:
            print(diagnostic_to_text(filename, diagnostic))

    return rc
