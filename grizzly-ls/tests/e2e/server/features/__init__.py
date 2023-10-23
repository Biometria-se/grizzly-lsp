import logging

from typing import Optional, Dict, Any
from pathlib import Path

from lsprotocol import types as lsp
from pygls.server import LanguageServer

from grizzly_ls.constants import FEATURE_INSTALL


def initialize(
    client: LanguageServer,
    root: Path,
    options: Optional[Dict[str, Any]] = None,
) -> None:
    assert root.is_file()

    root = root.parent.parent
    params = lsp.InitializeParams(
        process_id=1337,
        root_uri=root.as_uri(),
        capabilities=lsp.ClientCapabilities(
            workspace=None,
            text_document=None,
            window=None,
            general=None,
            experimental=None,
        ),
        client_info=None,
        locale=None,
        root_path=str(root),
        initialization_options=options,
        trace=None,
        workspace_folders=None,
        work_done_token=None,
    )

    for logger_name in ['pygls', 'parse', 'pip']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)

    logger = logging.getLogger()
    level = logger.getEffectiveLevel()
    try:
        logger.setLevel(logging.DEBUG)

        # INITIALIZE takes time...
        client.lsp.send_request(  # type: ignore
            lsp.INITIALIZE,
            params,
        ).result(timeout=299)

        client.lsp.send_request(FEATURE_INSTALL).result(timeout=299)  # type: ignore
    finally:
        logger.setLevel(level)


def open(client: LanguageServer, path: Path, text: Optional[str] = None) -> None:
    if text is None:
        text = path.read_text()

    client.lsp.notify(  # type: ignore
        lsp.TEXT_DOCUMENT_DID_OPEN,
        lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(
                uri=path.as_uri(),
                language_id='grizzly-gherkin',
                version=1,
                text=text,
            ),
        ),
    )
