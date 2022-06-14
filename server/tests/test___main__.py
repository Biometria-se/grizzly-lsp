import sys

from argparse import Namespace

import pytest

from _pytest.capture import CaptureFixture

from grizzly_vscode_ls.__main__ import parse_arguments


def test_parse_arguments(capsys: CaptureFixture[str]) -> None:
    sys.argv = ['grizzly-vscode-ls']

    args = parse_arguments()

    assert args == Namespace(socket=False, socket_port=4444, verbose=False, version=False)

    sys.argv = ['grizzly-vscode-ls', '--socket', '--socket-port', '5555', '--verbose']

    args = parse_arguments()

    assert args == Namespace(socket=True, socket_port=5555, verbose=True, version=False)

    sys.argv = ['grizzly-vscode-ls', '--version']

    with pytest.raises(SystemExit) as se:
        parse_arguments()
    assert se.value.code == 0

    capture = capsys.readouterr()

    assert capture.out == ''
    assert not capture.err == ''
