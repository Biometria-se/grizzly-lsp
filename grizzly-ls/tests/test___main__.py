import sys
import logging

from typing import Callable, cast
from argparse import Namespace

import pytest

from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from grizzly_ls.__main__ import parse_arguments, setup_logging, main as _main


def test_parse_arguments(capsys: CaptureFixture[str]) -> None:
    sys.argv = ['grizzly-ls']

    args = parse_arguments()

    assert args == Namespace(
        socket=False, socket_port=4444, verbose=False, version=False
    )

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
    logging_FileHandler_mock = mocker.patch(
        'grizzly_ls.__main__.logging.FileHandler', spec_set=logging.FileHandler
    )
    logging_StreamHandler_mock = mocker.patch(
        'grizzly_ls.__main__.logging.StreamHandler', spec_set=logging.StreamHandler
    )

    # <no args>
    arguments = Namespace(socket=False, verbose=False)

    setup_logging(arguments)

    assert logging_basicConfig_mock.call_count == 1
    _, kwargs = logging_basicConfig_mock.call_args_list[-1]
    assert kwargs.get('level', None) == logging.INFO
    assert kwargs.get('format', None) == '[%(asctime)s] %(levelname)s: %(message)s'
    handlers = kwargs.get('handlers', None)
    assert len(handlers) == 0
    assert logging_FileHandler_mock.call_count == 0
    assert logging_StreamHandler_mock.call_count == 0

    # --verbose
    arguments = Namespace(socket=False, verbose=True)

    setup_logging(arguments)

    assert logging_basicConfig_mock.call_count == 2
    _, kwargs = logging_basicConfig_mock.call_args_list[-1]
    assert kwargs.get('level', None) == logging.DEBUG
    assert kwargs.get('format', None) == '[%(asctime)s] %(levelname)s: %(message)s'
    handlers = kwargs.get('handlers', None)
    assert len(handlers) == 1
    assert logging_StreamHandler_mock.call_count == 0
    assert logging_FileHandler_mock.call_count == 1
    args, _ = logging_FileHandler_mock.call_args_list[-1]
    assert args[0] == 'grizzly-ls.log'

    # --socket
    arguments = Namespace(socket=True, verbose=False)

    setup_logging(arguments)

    assert logging_basicConfig_mock.call_count == 3
    _, kwargs = logging_basicConfig_mock.call_args_list[-1]
    assert kwargs.get('level', None) == logging.INFO
    assert kwargs.get('format', None) == '[%(asctime)s] %(levelname)s: %(message)s'
    handlers = kwargs.get('handlers', None)
    assert len(handlers) == 1
    assert logging_StreamHandler_mock.call_count == 1
    args, _ = logging_StreamHandler_mock.call_args_list[-1]
    assert args[0] is sys.stderr
    assert logging_FileHandler_mock.call_count == 1


def test_main(mocker: MockerFixture) -> None:
    main = cast(Callable[[], None], _main)
    mocker.patch(
        'grizzly_ls.__main__.setup_logging', return_value=None
    )  # no logging in test

    server_start_io_mock = mocker.patch(
        'grizzly_ls.__main__.GrizzlyLanguageServer.start_io', return_value=None
    )
    server_start_tcp = mocker.patch(
        'grizzly_ls.__main__.GrizzlyLanguageServer.start_tcp', return_value=None
    )

    # <no args>
    sys.argv = ['grizzly-ls']

    main()

    assert server_start_io_mock.call_count == 1
    args, _ = server_start_io_mock.call_args_list[-1]
    assert args[0] is sys.stdin.buffer
    assert args[1] is sys.stdout.buffer

    assert server_start_tcp.call_count == 0

    # --socket
    sys.argv = ['grizzly-ls', '--socket']

    main()

    assert server_start_io_mock.call_count == 1

    assert server_start_tcp.call_count == 1
    args, _ = server_start_tcp.call_args_list[-1]
    assert args[0] == '127.0.0.1'
    assert args[1] == 4444
