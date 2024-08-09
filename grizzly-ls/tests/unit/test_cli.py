from colorama import Fore
from lsprotocol import types as lsp

from grizzly_ls.cli import _get_severity_color, diagnostic_to_text


def test__get_severity_color() -> None:
    assert _get_severity_color(None) == Fore.RESET
    assert _get_severity_color(lsp.DiagnosticSeverity.Error) == Fore.RED
    assert _get_severity_color(lsp.DiagnosticSeverity.Information) == Fore.BLUE
    assert _get_severity_color(lsp.DiagnosticSeverity.Warning) == Fore.YELLOW
    assert _get_severity_color(lsp.DiagnosticSeverity.Hint) == Fore.CYAN


def test_diagnostic_to_text() -> None:
    diagnostic = lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=9, character=10),
            end=lsp.Position(line=9, character=15),
        ),
        message='foobar',
        severity=lsp.DiagnosticSeverity.Warning,
        source='test_diagnostic_to_text',
    )

    assert diagnostic_to_text('foobar.feature', diagnostic, max_length=14) == f'foobar.feature:10:11    {Fore.YELLOW}warning{Fore.RESET} foobar'
