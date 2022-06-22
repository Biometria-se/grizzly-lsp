from typing import Callable, Optional, Any
class Matcher:
    pattern: str

class ParseMatcher(Matcher):
    def __init__(self, func: Callable[..., Any], pattern: str, step_type: Optional[str] = ...) -> None: ...

    ...
