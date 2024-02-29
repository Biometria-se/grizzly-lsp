from unittest.mock import ANY

from grizzly_ls.server.progress import Progress
from pytest_mock import MockerFixture

from tests.fixtures import LspFixture


def test_progress(lsp_fixture: LspFixture, mocker: MockerFixture) -> None:
    server = lsp_fixture.server

    progress = Progress(server.progress, title='test')

    assert progress.progress is server.progress
    assert progress.title == 'test'
    assert isinstance(progress.token, str)

    report_spy = mocker.spy(progress, 'report')
    progress_create_mock = mocker.patch.object(progress.progress, 'create', return_value=None)
    progress_begin_mock = mocker.patch.object(progress.progress, 'begin', return_value=None)
    progress_end_mock = mocker.patch.object(
        progress.progress,
        'end',
        return_value=None,
    )
    progress_report_mock = mocker.patch.object(progress.progress, 'report', return_value=None)

    with progress as p:
        p.report('first', 50)
        p.report('second', 99)

    progress_create_mock.assert_called_once_with(progress.token, progress.callback)
    progress_begin_mock.assert_called_once_with(progress.token, ANY)
    progress_end_mock.assert_called_once_with(progress.token, ANY)

    assert progress_report_mock.call_count == 3
    assert report_spy.call_count == 3
