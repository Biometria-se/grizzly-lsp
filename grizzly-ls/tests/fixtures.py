import os
import asyncio

from types import TracebackType
from typing import Literal, Optional, Type
from threading import Thread
from pathlib import Path

from pytest_mock import MockerFixture

from pygls.server import LanguageServer
from pygls.lsp.methods import EXIT
from behave.runner_util import reset_runtime
from grizzly_ls.server import GrizzlyLanguageServer


class LspFixture:
    client: LanguageServer
    server: GrizzlyLanguageServer

    _server_thread: Thread
    _client_thread: Thread
    _mocker: MockerFixture

    datadir: Path


    def __init__(self, mocker: MockerFixture) -> None:
        self._mocker = mocker

    def __enter__(self) -> 'LspFixture':
        reset_runtime(reset_matchers=False)
        cstdio, cstdout = os.pipe()
        sstdio, sstdout = os.pipe()

        def start(ls: LanguageServer, fdr: int, fdw: int) -> None:
            try:
                ls.start_io(os.fdopen(fdr, 'rb'), os.fdopen(fdw, 'wb'))  # type: ignore
            except:
                pass

        self.server = GrizzlyLanguageServer(asyncio.new_event_loop())  # type: ignore
        self._server_thread = Thread(target=start, args=(self.server, cstdio, sstdout), daemon=True)
        self._server_thread.start()

        self.client = LanguageServer(asyncio.new_event_loop())
        self._client_thread = Thread(target=start, args=(self.client, sstdio, cstdout), daemon=True)
        self._client_thread.start()

        self.datadir = (Path(__file__) / '..' / '..' / '..' / 'tests' / 'project').resolve()

        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], traceback: Optional[TracebackType]) -> Literal[True]:
        self.server.send_notification(EXIT)
        self.client.send_notification(EXIT)
        
        self._server_thread.join(timeout=2.0)
        self._client_thread.join(timeout=2.0)

        return True

