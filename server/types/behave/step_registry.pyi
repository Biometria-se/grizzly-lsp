from typing import Dict, List
from behave.matchers import ParseMatcher

class StepRegistry:
    steps: Dict[str, List[ParseMatcher]]

registry: StepRegistry
