from typing import Callable, Optional, Any, Dict, Tuple

class Matcher:
    pattern: str
    func: Callable[[Tuple[Any, ...]], Any]

    ...

class ParseMatcher(Matcher):
    custom_types: Dict[str, Callable[[str], Any]]
    def __init__(self, func: Callable[..., Any], pattern: str, step_type: Optional[str] = ...) -> None: ...

    ...
