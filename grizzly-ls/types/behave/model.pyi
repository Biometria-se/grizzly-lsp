from typing import List, Optional

class Row:
    cells: List[str]

class Table:
    headings: List[str]
    rows: List[Row]

class Step:
    name: str
    text: Optional[str]
    keyword: str
    table: Optional[Table]

class Scenario:
    name: str
    steps: List[Step]
    line: int
    ...

class Feature:
    scenarios: List[Scenario]
    ...
