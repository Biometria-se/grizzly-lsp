#!/usr/bin/env python

import sys
import subprocess

from typing import List, Dict
from os import path
from json import loads as jsonloads
from io import StringIO

import requests

from piplicenses import CustomNamespace, FormatArg, FromArg, OrderArg, create_output_string  # type: ignore
from pytablewriter import MarkdownTableWriter  # type: ignore

URL_MAP: Dict[str, str] = {}

REPO_ROOT = path.realpath(path.join(path.dirname(__file__), '..'))


def client_vscode_generate_license_table() -> List[str]:
    output = subprocess.check_output(
        ['npm', 'run', 'licenses'],
        shell=False,
        encoding='utf-8',
        cwd='./client/vscode',
    ).split('\n')

    licenses = jsonloads(output[4])

    headers = ['Name', 'Version', 'License']
    table_contents: List[List[str]] = []

    for license in licenses:
        name = license['name']
        name = f'[{name}]({license["link"]})'

        table_contents.append(
            [
                name,
                license['installedVersion'],
                license['licenseType'],
            ]
        )

    writer = MarkdownTableWriter(
        headers=headers,
        value_matrix=table_contents,
        margin=1,
    )

    writer.stream = StringIO()
    writer.write_table()  # type: ignore

    license_table = [f'{row}\n' for row in writer.stream.getvalue().strip().split('\n')]  # type: ignore

    return license_table


def server_generate_license_table() -> List[str]:
    args = CustomNamespace()
    args.format_ = FormatArg.JSON
    args.from_ = FromArg.MIXED
    args.order = OrderArg.LICENSE
    args.summary = False
    args.with_authors = False
    args.with_urls = True
    args.with_description = False
    args.with_license_file = True
    args.no_license_path = False
    args.with_license_file = False
    args.ignore_packages = []
    args.packages = []
    args.fail_on = None
    args.allow_only = None
    args.with_system = False
    args.filter_strings = False

    licenses = jsonloads(create_output_string(args))  # type: ignore
    headers = ['Name', 'Version', 'License']

    table_contents: List[List[str]] = []

    for license in licenses:
        name = license['Name']
        # https://stackoverflow.com/questions/39577984/what-is-pkg-resources-0-0-0-in-output-of-pip-freeze-command
        if name.startswith('grizzly-') or name in ['pkg-resources']:
            continue

        if license['URL'] == 'UNKNOWN':
            try:
                response = requests.get(f'https://pypi.org/pypi/{name}/json')

                if response.status_code != 200:
                    raise ValueError(f'{response.url} returned {response.status_code}')

                result = jsonloads(response.text)

                info = result.get('info', None) or {}
                project_urls = info.get('project_urls', None) or {}

                url = project_urls.get(
                    'Homepage',
                    project_urls.get(
                        'Home',
                        info.get(
                            'project_url',
                            info.get(
                                'package_url',
                                URL_MAP.get(name, None),
                            ),
                        ),
                    ),
                )

                if url is None:
                    raise ValueError(f'no URL found on {response.url} or in static map')

                license['URL'] = url
            except Exception as e:
                print(
                    f"!! you need to find an url for package '{name}': {str(e)}",
                    file=sys.stderr,
                )
                sys.exit(1)

        name = f'[{name}]({license["URL"]})'

        table_contents.append(
            [
                name,
                license['Version'],
                license['License'],
            ]
        )

    writer = MarkdownTableWriter(
        headers=headers,
        value_matrix=table_contents,
        margin=1,
    )

    writer.stream = StringIO()
    writer.write_table()  # type: ignore

    license_table = [f'{row}\n' for row in writer.stream.getvalue().strip().split('\n')]  # type: ignore

    return license_table


def main() -> int:
    with open(path.join(REPO_ROOT, 'LICENSE.md')) as fd:
        contents = fd.readlines()

    server_license_table = server_generate_license_table()
    client_vscode_license_table = client_vscode_generate_license_table()

    contents[0] = f'#{contents[0]}'
    license_contents = (
        contents
        + ['\n', '## Third party licenses\n', '\n', '### Server\n', '\n']
        + server_license_table[:-1]
        + ['\n### Client\n\n', '#### Visual Studio Code\n\n']
        + client_vscode_license_table
    )

    print(''.join(license_contents))

    return 0


if __name__ == '__main__':
    sys.exit(main())
