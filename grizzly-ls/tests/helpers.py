from typing import List

from lsprotocol.types import CompletionItemKind, CompletionItem


def normalize_completion_item(
    steps: List[CompletionItem],
    kind: CompletionItemKind,
    attr: str = 'label',
) -> List[str]:
    labels: List[str] = []
    for step in steps:
        assert step.kind == kind
        value = getattr(step, attr)
        labels.append(value)

    return labels


def normalize_completion_text_edit(
    steps: List[CompletionItem],
    kind: CompletionItemKind,
) -> List[str]:
    labels: List[str] = []
    for step in steps:
        assert step.kind == kind
        assert step.text_edit is not None
        labels.append(step.text_edit.new_text)

    return labels
