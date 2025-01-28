from __future__ import annotations

from typing import List
from pathlib import Path
from contextlib import suppress

from jinja2 import Environment

from grizzly_ls.utils import ScenarioTag
from grizzly_ls.text import remove_if_statements


def render_gherkin(path: str, content: str, *, raw: bool = False) -> str:
    feature_file = Path(path)
    environment = Environment(autoescape=False, extensions=[ScenarioTag])
    environment.extend(feature_file=feature_file, ignore_errors=True)

    content = remove_if_statements(content)
    template = environment.from_string(content)
    content = template.render()

    if not raw:
        # <!-- sanatize content
        buffer: List[str] = []
        for line in content.splitlines():
            # make any html tag characters in comments are replaced with respective html entity code
            with suppress(Exception):
                if line.lstrip()[0] == '#':
                    line = line.replace('<', '&lt;')
                    line = line.replace('>', '&gt;')

            buffer.append(line)
        # // -->
        return '\n'.join(buffer)

    return content
