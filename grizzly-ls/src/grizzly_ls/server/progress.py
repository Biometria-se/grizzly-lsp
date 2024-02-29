from __future__ import annotations

from typing import Any, Optional, Type
from types import TracebackType
from uuid import uuid4

from lsprotocol import types as lsp
from pygls.progress import Progress as PyglsProgress


class Progress:
    progress: PyglsProgress
    title: str
    token: str

    def __init__(self, progress: PyglsProgress, title: str) -> None:
        self.progress = progress
        self.title = title
        self.token = str(uuid4())

    @staticmethod
    def callback(*args: Any, **kwargs: Any) -> None:
        return  # pragma: no cover

    def __enter__(self) -> Progress:
        self.progress.create(self.token, self.__class__.callback)  # type: ignore

        self.progress.begin(
            self.token,
            lsp.WorkDoneProgressBegin(title=self.title, percentage=0, cancellable=False),
        )

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        self.report(None, 100)

        self.progress.end(self.token, lsp.WorkDoneProgressEnd())

        return exc is None

    def report(self, message: Optional[str] = None, percentage: Optional[int] = None) -> None:
        self.progress.report(
            self.token,
            lsp.WorkDoneProgressReport(message=message, percentage=percentage),
        )
