from typing import Optional

from behave.model import Feature

def parse_feature(data: str, language: Optional[str] = None, filename: Optional[str] = None) -> Optional[Feature]: ...

class ParserError(Exception):
    line: Optional[int]
    line_text: Optional[str]
    filename: Optional[str]

    ...
