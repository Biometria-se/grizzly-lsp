import typing as t
from pathlib import Path

from jinja2.ext import Extension
from jinja2 import Environment

class GrizzlyEnvironment(Environment):
    feature_file: Path
    indent: int

class BaseTemplateTag(Extension):
    def preprocess(self, source: str, name: t.Optional[str], filename: t.Optional[str] = None) -> str: ...

class StandaloneTag(BaseTemplateTag):
    environment: GrizzlyEnvironment
