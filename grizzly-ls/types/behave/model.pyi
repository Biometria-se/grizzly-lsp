from typing import List

class Step: ...

class Scenario:
    name: str
    steps: List[Step]
    ...

class Feature:
    scenarios: List[Scenario]
    ...
