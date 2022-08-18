from typing import Callable, Optional, Any, Dict

class Matcher:
    pattern: str

    ...

class ParseMatcher(Matcher):
    custom_types: Dict[str, Callable[[str], Any]]
    def __init__(
        self, func: Callable[..., Any], pattern: str, step_type: Optional[str] = ...
    ) -> None: ...

    ...
