from typing import Optional, cast
from pathlib import Path

from lsprotocol import types as lsp
from pygls.server import LanguageServer

from tests.fixtures import LspFixture
from tests.e2e.server.features import initialize, open


def hover(
    client: LanguageServer,
    path: Path,
    position: lsp.Position,
    content: Optional[str] = None,
) -> Optional[lsp.Hover]:
    path = path / 'features' / 'project.feature'

    initialize(client, path, options=None)
    open(client, path, content)

    params = lsp.HoverParams(
        text_document=lsp.TextDocumentIdentifier(
            uri=path.as_uri(),
        ),
        position=position,
    )

    response = client.lsp.send_request(lsp.TEXT_DOCUMENT_HOVER, params).result(timeout=3)  # type: ignore

    assert response is None or isinstance(response, lsp.Hover)

    return cast(Optional[lsp.Hover], response)


def test_hover(lsp_fixture: LspFixture) -> None:
    client = lsp_fixture.client

    response = hover(client, lsp_fixture.datadir, lsp.Position(line=2, character=31))

    assert response is not None
    assert response.range is not None

    assert response.range.end.character == 85
    assert response.range.end.line == 2
    assert response.range.start.character == 4
    assert response.range.start.line == 2
    assert isinstance(response.contents, lsp.MarkupContent)
    assert response.contents.kind == lsp.MarkupKind.Markdown
    assert (
        response.contents.value
        == '''Set which type of users the scenario should use and which `host` is the target,
together with `weight` of the user (how many instances of this user should spawn relative to others).

Example:
```gherkin
Given a user of type "RestApi" with weight "2" load testing "..."
Given a user of type "MessageQueue" with weight "1" load testing "..."
Given a user of type "ServiceBus" with weight "1" load testing "..."
Given a user of type "BlobStorage" with weight "4" load testing "..."
```

Args:

* user_class_name `str`: name of an implementation of users, with or without `User`-suffix
* weight_value `str`: weight value for the user, default is `1` (see [writing a locustfile](http://docs.locust.io/en/stable/writing-a-locustfile.html#weight-attribute))
* host `str`: an URL for the target host, format depends on which users is specified
'''
    )

    response = hover(client, lsp_fixture.datadir, lsp.Position(line=0, character=1))

    assert response is None

    response = hover(
        client,
        lsp_fixture.datadir,
        lsp.Position(line=6, character=12),
        content='''Feature:
Scenario: test
Given a user of type "RestApi" load testing "http://localhost"
Then do something
"""
{
"hello": "world"
}
"""''',
    )

    assert response is None
