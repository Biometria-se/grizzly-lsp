import logging

from typing import Any, Tuple, Dict

from pygls.server import LanguageServer
from pygls.lsp.methods import COMPLETION, INITIALIZE
from pygls.lsp.types import CompletionParams, CompletionList, InitializeParams


class GrizzlyLanguageServer(LanguageServer):
    logger: logging.Logger = logging.getLogger(__name__)

    def __init__(self, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]) -> None:
        super().__init__(*args, **kwargs)  # type: ignore

        @self.feature(INITIALIZE)
        def initialize(params: InitializeParams) -> None:
            self.logger.debug(f'got: {params}')

        @self.feature(COMPLETION)
        def completions(params: CompletionParams) -> CompletionList:
            self.logger.debug(f'got: {params}')
            return CompletionList(
                is_incomplete=False,
                item=[

                ],
            )
