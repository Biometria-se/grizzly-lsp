from typing import List

from pygls.lsp.types import CompletionItemKind, CompletionItem


def normalize_completion_item(
    steps: List[CompletionItem], kind: CompletionItemKind
) -> List[str]:
    labels: List[str] = []
    for step in steps:
        assert step.kind == kind
        labels.append(step.label)

    return labels
