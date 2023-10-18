from typing import Callable, Optional
from dataclasses import dataclass, field


@dataclass
class Step:
    keyword: str
    expression: str
    func: Callable[..., None]
    help: Optional[str] = field(default=None)
