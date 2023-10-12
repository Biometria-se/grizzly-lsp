import logging
import re
import inspect

from typing import Optional, Dict, Any, List, cast
from pathlib import Path
from tempfile import gettempdir
from shutil import rmtree

import gevent.monkey  # type: ignore

# monkey patch functions to short-circuit them (causes problems in this context)
gevent.monkey.patch_all = lambda: None

from _pytest.logging import LogCaptureFixture

from pygls.server import LanguageServer
from lsprotocol import types as lsp

from tests.fixtures import LspFixture
from grizzly_ls import __version__
from grizzly_ls.server import GrizzlyLanguageServer


class TestE2eGrizzlyLangageServerFeatures:
    def _initialize(
        self,
        client: LanguageServer,
        root: Path,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        assert root.is_file()

        file = root
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

            client.lsp.send_request(  # type: ignore
                lsp.INITIALIZE,
                params,
            ).result(timeout=89)

            client.lsp.send_request(  # type: ignore
                GrizzlyLanguageServer.FEATURE_INSTALL,
                {'external': file.as_uri(), 'fsPath': str(file)},
            ).result(timeout=89)
        finally:
            logger.setLevel(level)

    def _open(
        self, client: LanguageServer, path: Path, text: Optional[str] = None
    ) -> None:
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

    def _completion(
        self,
        client: LanguageServer,
        path: Path,
        content: str,
        options: Optional[Dict[str, str]] = None,
        context: Optional[lsp.CompletionContext] = None,
        position: Optional[lsp.Position] = None,
    ) -> Optional[lsp.CompletionList]:
        path = path / 'features' / 'project.feature'

        self._initialize(client, path, options)
        self._open(client, path, content)

        lines = content.split('\n')
        line = len(lines) - 1
        character = len(lines[-1])

        if character < 0:
            character = 0

        if position is None:
            position = lsp.Position(line=line, character=character)

        params = lsp.CompletionParams(
            text_document=lsp.TextDocumentIdentifier(
                uri=path.as_uri(),
            ),
            position=position,
            context=context,
            partial_result_token=None,
            work_done_token=None,
        )

        logger = logging.getLogger()
        level = logger.getEffectiveLevel()
        try:
            logger.setLevel(logging.DEBUG)
            response = client.lsp.send_request(lsp.TEXT_DOCUMENT_COMPLETION, params).result(timeout=3)  # type: ignore
        finally:
            logger.setLevel(level)

        assert response is None or isinstance(response, lsp.CompletionList)

        return cast(Optional[lsp.CompletionList], response)

    def _hover(
        self,
        client: LanguageServer,
        path: Path,
        position: lsp.Position,
        content: Optional[str] = None,
    ) -> Optional[lsp.Hover]:
        path = path / 'features' / 'project.feature'

        self._initialize(client, path, options=None)
        self._open(client, path, content)

        params = lsp.HoverParams(
            text_document=lsp.TextDocumentIdentifier(
                uri=path.as_uri(),
            ),
            position=position,
        )

        response = client.lsp.send_request(lsp.TEXT_DOCUMENT_HOVER, params).result(timeout=3)  # type: ignore

        assert response is None or isinstance(response, lsp.Hover)

        return cast(Optional[lsp.Hover], response)

    def _definition(
        self,
        client: LanguageServer,
        path: Path,
        position: lsp.Position,
        content: Optional[str] = None,
    ) -> Optional[List[lsp.LocationLink]]:
        path = path / 'features' / 'project.feature'

        self._initialize(client, path, options=None)
        self._open(client, path, content)

        params = lsp.DefinitionParams(
            text_document=lsp.TextDocumentIdentifier(
                uri=path.as_uri(),
            ),
            position=position,
        )

        response = client.lsp.send_request(lsp.TEXT_DOCUMENT_DEFINITION, params).result(timeout=3)  # type: ignore

        assert response is None or isinstance(response, list)

        return cast(Optional[List[lsp.LocationLink]], response)

    def test_initialize(self, lsp_fixture: LspFixture) -> None:
        client = lsp_fixture.client
        server = lsp_fixture.server

        assert server.steps == {}

        virtual_environment = Path(gettempdir()) / 'grizzly-ls-project'

        if virtual_environment.exists():
            rmtree(virtual_environment)

        original_settings = server.client_settings.copy()

        try:
            self._initialize(
                client,
                lsp_fixture.datadir / 'features' / 'project.feature',
                options={
                    'variable_pattern': [
                        'hello "([^"]*)"!$',
                        'foo bar is a (nice|bad) word',
                        '.*and they lived (happy|unfortunate) ever after',
                        '^foo(bar)$',
                    ]
                },
            )

            assert not server.steps == {}
            assert isinstance(server.variable_pattern, re.Pattern)
            assert '^.*hello "([^"]*)"!$' in server.variable_pattern.pattern
            assert '^.*foo bar is a (nice|bad) word$' in server.variable_pattern.pattern
            assert (
                '^.*and they lived (happy|unfortunate) ever after$'
                in server.variable_pattern.pattern
            )
            assert '^foo(bar)$' in server.variable_pattern.pattern
            assert (
                server.variable_pattern.pattern.count('^') == 4 + 1
            )  # first pattern has ^ in the pattern...
            assert server.variable_pattern.pattern.count('(') == 5
            assert server.variable_pattern.pattern.count(')') == 5

            keywords = list(server.steps.keys())

            for keyword in ['given', 'then', 'when']:
                assert keyword in keywords

            assert 'Feature' not in server.keywords  # already used once in feature file
            assert 'Background' not in server.keywords  # - " -
            assert 'And' in server.keywords  # just an alias for Given, but we need it
            assert 'Scenario' in server.keywords  # can be used multiple times
            assert 'Given' in server.keywords  # - " -
            assert 'When' in server.keywords
        finally:
            server.client_settings = original_settings
            server.variable_pattern = server.__class__.variable_pattern

    def test_completion_keywords(self, lsp_fixture: LspFixture) -> None:
        client = lsp_fixture.client

        def filter_keyword_properties(
            items: List[lsp.CompletionItem],
        ) -> List[Dict[str, Any]]:
            return [
                {
                    'label': item.label,
                    'kind': item.kind,
                    'text_edit': item.text_edit.new_text
                    if item.text_edit is not None
                    else None,
                }
                for item in items
            ]

        # partial match, keyword containing 'B'
        response = self._completion(
            client,
            lsp_fixture.datadir,
            ''''Feature:
Scenario:
    B''',
            options=None,
        )

        assert response is not None
        assert not response.is_incomplete
        assert filter_keyword_properties(response.items) == [
            {'label': 'Background', 'kind': 14, 'text_edit': 'Background: '},
            {
                'label': 'But',
                'kind': 14,
                'text_edit': 'But ',
            },
        ]

        # partial match, keyword containing 'en'
        response = self._completion(
            client,
            lsp_fixture.datadir,
            '''Feature:
Scenario:
    en''',
            options=None,
        )
        assert response is not None
        assert not response.is_incomplete
        assert filter_keyword_properties(response.items) == [
            {
                'label': 'Given',
                'kind': 14,
                'text_edit': 'Given ',
            },
            {
                'label': 'Scenario',
                'kind': 14,
                'text_edit': 'Scenario: ',
            },
            {
                'label': 'Scenario Outline',
                'kind': 14,
                'text_edit': 'Scenario Outline: ',
            },
            {
                'label': 'Scenario Template',
                'kind': 14,
                'text_edit': 'Scenario Template: ',
            },
            {
                'label': 'Scenarios',
                'kind': 14,
                'text_edit': 'Scenarios: ',
            },
            {
                'label': 'Then',
                'kind': 14,
                'text_edit': 'Then ',
            },
            {
                'label': 'When',
                'kind': 14,
                'text_edit': 'When ',
            },
        ]

        # all keywords
        response = self._completion(client, lsp_fixture.datadir, '', options=None)
        assert response is not None
        assert not response.is_incomplete
        unexpected_kinds = [k.kind for k in response.items if k.kind != 14]
        assert len(unexpected_kinds) == 0
        labels = [k.label for k in response.items]
        text_edits = [
            k.text_edit.new_text for k in response.items if k.text_edit is not None
        ]
        assert all([True if label is not None else False for label in labels])
        assert labels == ['Feature']
        assert text_edits == ['Feature: ']

    def test_completion_steps(self, lsp_fixture: LspFixture) -> None:
        client = lsp_fixture.client

        # all Given/And steps
        for keyword in ['Given', 'And']:
            response = self._completion(
                client, lsp_fixture.datadir, keyword, options=None
            )
            assert response is not None
            assert not response.is_incomplete
            unexpected_kinds = list(
                filter(
                    lambda s: s != 3,
                    map(lambda s: s.kind, response.items),
                )
            )
            assert len(unexpected_kinds) == 0

            labels = [
                s.text_edit.new_text for s in response.items if s.text_edit is not None
            ]
            assert len(labels) > 0
            assert all([True if label is not None else False for label in labels])

            assert 'ask for value of variable "$1"' in labels
            assert 'spawn rate is "$1" user per second' in labels
            assert 'spawn rate is "$1" users per second' in labels
            assert 'a user of type "$1" with weight "$2" load testing "$3"' in labels

        response = self._completion(
            client, lsp_fixture.datadir, 'Given value', options=None
        )
        assert response is not None
        assert not response.is_incomplete
        unexpected_kinds = list(
            filter(
                lambda s: s != 3,
                map(lambda s: s.kind, response.items),
            )
        )
        assert len(unexpected_kinds) == 0

        labels = list(
            map(lambda s: s.label, response.items),
        )
        assert len(labels) > 0
        assert all([True if label is not None else False for label in labels])

        assert 'ask for value of variable ""' in labels
        assert 'value for variable "" is ""'

        response = self._completion(client, lsp_fixture.datadir, 'Given a user of')
        assert response is not None
        assert not response.is_incomplete
        unexpected_kinds = list(
            filter(
                lambda s: s != 3,
                map(lambda s: s.kind, response.items),
            )
        )
        assert len(unexpected_kinds) == 0

        labels = list(
            map(lambda s: s.label, response.items),
        )
        assert len(labels) > 0
        assert all([True if label is not None else False for label in labels])

        assert 'a user of type "" with weight "" load testing ""' in labels
        assert 'a user of type "" load testing ""' in labels

        response = self._completion(
            client, lsp_fixture.datadir, 'Then parse date "{{ datetime.now() }}"'
        )
        assert response is not None
        assert not response.is_incomplete

        labels = list(
            map(lambda s: s.label, response.items),
        )
        insert_texts = [
            s.text_edit.new_text for s in response.items if s.text_edit is not None
        ]

        assert labels == ['parse date "{{ datetime.now() }}" and save in variable ""']
        assert insert_texts == [' and save in variable "$1"']

    def test_completion_variable_names(
        self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
    ) -> None:
        client = lsp_fixture.client

        content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then parse date "{{'''
        response = self._completion(client, lsp_fixture.datadir, content)

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' price }}"', ' foo }}"', ' test }}"', ' bar }}"']
        )
        assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

        content = '''Feature: test
    Scenario: test1
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then log message "{{

    Scenario: test2
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "weight1" is "200"
        And value for variable "hello1" is "bar"
        And value for variable "test1" is "False"
        And ask for value of variable "world1"

        Then log message "{{ "
        Then log message "{{ w"

    Scenario: test3
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "weight2" is "200"
        And value for variable "hello2" is "bar"
        And value for variable "test2" is "False"
        And ask for value of variable "world2"

        Then log message "{{ }}"
        Then log message "{{ w}}"'''

        # <!-- Scenario: test1
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=8, character=28),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' price }}"', ' foo }}"', ' test }}"', ' bar }}"']
        )
        assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])
        # // -->

        # <!-- Scenario: test2
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=17, character=28),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' weight1 }}', ' hello1 }}', ' test1 }}', ' world1 }}']
        )
        assert sorted(labels) == sorted(['weight1', 'hello1', 'test1', 'world1'])

        # partial variable name
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=18, character=30),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(['weight1 }}', 'world1 }}'])
        assert sorted(labels) == sorted(['weight1', 'world1'])
        # // -->

        # <!-- Scenario: test3
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=27, character=28),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' weight2', ' hello2', ' test2', ' world2']
        )
        assert sorted(labels) == sorted(['weight2', 'hello2', 'test2', 'world2'])

        # partial variable name
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=28, character=30),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(['weight2 ', 'world2 '])
        assert sorted(labels) == sorted(['weight2', 'world2'])
        # // -->

        content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then parse date "{{" and save in variable ""'''
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=8, character=27),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' price }}', ' foo }}', ' test }}', ' bar }}']
        )
        assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

        content = '''Feature: test
    Scenario: test
        Given a user of type "Dummy" load testing "dummy://test"
        And value for variable "price" is "200"
        And value for variable "foo" is "bar"
        And value for variable "test" is "False"
        And ask for value of variable "bar"

        Then send request "test/request.j2.json" with name "{{" to endpoint ""
        Then send request "{{}}" with name "" to endpoint ""'''
        response = self._completion(
            client,
            lsp_fixture.datadir,
            content,
            position=lsp.Position(line=8, character=62),
        )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [' price }}', ' foo }}', ' test }}', ' bar }}']
        )
        assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

        with caplog.at_level(logging.DEBUG):
            response = self._completion(
                client,
                lsp_fixture.datadir,
                content,
                position=lsp.Position(line=9, character=29),
            )

        assert response is not None

        labels = list(
            map(lambda s: s.label, response.items),
        )
        text_edits = list(
            [s.text_edit.new_text for s in response.items if s.text_edit is not None]
        )

        assert sorted(text_edits) == sorted(
            [
                ' price ',
                ' foo ',
                ' test ',
                ' bar ',
            ]
        )
        assert sorted(labels) == sorted(['price', 'foo', 'test', 'bar'])

    def test_hover(self, lsp_fixture: LspFixture) -> None:
        client = lsp_fixture.client

        response = self._hover(
            client, lsp_fixture.datadir, lsp.Position(line=2, character=31)
        )

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
            == '''Sets which type of users the scenario should use and which `host` is the target,
together with `weight` of the user (how many instances of this user should spawn relative to others).

Example:

``` gherkin
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

        response = self._hover(
            client, lsp_fixture.datadir, lsp.Position(line=0, character=1)
        )

        assert response is None

        response = self._hover(
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

    def test_definition(
        self, lsp_fixture: LspFixture, caplog: LogCaptureFixture
    ) -> None:
        client = lsp_fixture.client

        content = '''Feature:
    Scenario: test
        Given a user of type "RestApi" load testing "http://localhost"
        Then post request "test/test.txt" with name "test request" to endpoint "/api/test"
'''
        # <!-- hover "Scenario", no definition
        response = self._definition(
            client,
            lsp_fixture.datadir,
            lsp.Position(line=1, character=9),
            content,
        )

        assert response is None
        # // -->

        # <!-- hover the first variable in "Given a user of type..."
        response = self._definition(
            client,
            lsp_fixture.datadir,
            lsp.Position(line=2, character=30),
            content,
        )

        assert response is not None
        assert len(response) == 1
        actual_definition = response[0]

        from grizzly.steps.scenario.user import step_user_type

        file_location = Path(inspect.getfile(step_user_type))
        _, lineno = inspect.getsourcelines(step_user_type)

        assert actual_definition.target_uri == file_location.as_uri()
        assert actual_definition.target_range == lsp.Range(
            start=lsp.Position(line=lineno, character=0),
            end=lsp.Position(line=lineno, character=0),
        )
        assert (
            actual_definition.target_range == actual_definition.target_selection_range
        )
        assert actual_definition.origin_selection_range == lsp.Range(
            start=lsp.Position(line=2, character=8),
            end=lsp.Position(line=2, character=70),
        )
        # // -->

        # <!-- hover "test/test.txt" in "Then post a request..."
        request_payload_dir = lsp_fixture.datadir / 'features' / 'requests' / 'test'
        request_payload_dir.mkdir(exist_ok=True, parents=True)
        try:
            test_txt_file = request_payload_dir / 'test.txt'
            test_txt_file.write_text('hello world!')
            with caplog.at_level(logging.DEBUG):
                lsp_logger = logging.getLogger('pygls')
                lsp_logger.setLevel(logging.CRITICAL)
                response = self._definition(
                    client,
                    lsp_fixture.datadir,
                    lsp.Position(line=3, character=27),
                    content,
                )
            assert response is not None
            assert len(response) == 1
            actual_definition = response[0]
            assert actual_definition.target_uri == test_txt_file.as_uri()
            assert actual_definition.target_range == lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=0),
            )
            assert (
                actual_definition.target_selection_range
                == actual_definition.target_range
            )
            assert actual_definition.origin_selection_range is not None
            assert actual_definition.origin_selection_range == lsp.Range(
                start=lsp.Position(line=3, character=27),
                end=lsp.Position(line=3, character=40),
            )
        # // -->
        finally:
            rmtree(request_payload_dir)
