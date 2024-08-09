from __future__ import annotations

from typing import List, TYPE_CHECKING
from pathlib import Path
from contextlib import suppress

from jinja2 import Environment

from grizzly_ls.utils import OnlyScenarioTag

if TYPE_CHECKING:
    from logging import Logger


def render_gherkin(path: str, content: str, logger: Logger) -> str:
    feature_file = Path(path)
    OnlyScenarioTag.logger = logger
    environment = Environment(autoescape=False, extensions=[OnlyScenarioTag])
    environment.extend(feature_file=feature_file)
    template = environment.from_string(content)
    content = template.render()
    buffer: List[str] = []
    # <!-- sanatize content
    for line in content.splitlines():
        # make any html tag characters in comments are replaced with respective html entity code
        with suppress(Exception):
            if line.lstrip()[0] == '#':
                line = line.replace('<', '&lt;')
                line = line.replace('>', '&gt;')

        buffer.append(line)
    # // -->

    return '\n'.join(buffer)
