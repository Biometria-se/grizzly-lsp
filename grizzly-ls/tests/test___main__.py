import sys
import logging

from argparse import Namespace

import pytest

from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from grizzly_ls.__main__ import parse_arguments, setup_logging


def test_parse_arguments(capsys: CaptureFixture[str]) -> None:
    sys.argv = ['grizzly-ls']

    args = parse_arguments()

    assert args == Namespace(socket=False, socket_port=4444, verbose=False, version=False)

    sys.argv = ['grizzly-ls', '--socket', '--socket-port', '5555', '--verbose']

    args = parse_arguments()

    assert args == Namespace(socket=True, socket_port=5555, verbose=True, version=False)

    sys.argv = ['grizzly-ls', '--version']

    with pytest.raises(SystemExit) as se:
        parse_arguments()
    assert se.value.code == 0

    capture = capsys.readouterr()

    assert capture.out == ''
    assert not capture.err == ''


def test_setup_logging(mocker: MockerFixture) -> None:
    logging_basicConfig_mock = mocker.patch('grizzly_ls.__main__.logging.basicConfig')
    logging_FileHandler_mock = mocker.patch('grizzly_ls.__main__.logging.FileHandler', spec_set=logging.FileHandler)

    # --verbose
    args = Namespace(socket=False, verbose=True)

    setup_logging(args)

    assert logging_basicConfig_mock.call_count == 1
    _, kwargs = logging_basicConfig_mock.call_args_list[-1]
    assert kwargs.get('level', None) == logging.DEBUG
    assert kwargs.get('format', None) == '[%(asctime)s] %(levelname)s: %(message)s'
    handlers = kwargs.get('handlers', None)
    assert len(handlers) == 1
    assert logging_FileHandler_mock.call_count == 1
    args, _ = logging_FileHandler_mock.call_args_list[-1]
    assert args[0] == 'grizzly-ls.log'
