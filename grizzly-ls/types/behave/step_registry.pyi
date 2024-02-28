from typing import Dict, List, Optional, Any
from behave.matchers import ParseMatcher

class StepRegistry:
    steps: Dict[str, List[ParseMatcher]]

registry: StepRegistry

def setup_step_decorators(run_context: Optional[Dict[str, Any]] = ..., registry: StepRegistry = ...) -> None: ...
