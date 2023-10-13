import parse

from typing import List
from enum import Enum

from lsprotocol.types import CompletionItemKind, CompletionItem
from grizzly_extras.text import permutation, PermutationEnum
from grizzly.types import MessageDirection


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


class DummyEnum(PermutationEnum):
    HELLO = 0
    WORLD = 1
    FOO = 2
    BAR = 3

    @classmethod
    def from_string(cls, value: str) -> 'DummyEnum':
        for enum_value in cls:
            if enum_value.name.lower() == value.lower():
                return enum_value

        raise ValueError(f'{value} is not a valid value')


class DummyEnumNoFromString(PermutationEnum):
    ERROR = 0

    @classmethod
    def magic(cls, value: str) -> str:
        return value


class DummyEnumNoFromStringType(Enum):
    ERROR = 1

    @classmethod
    def from_string(cls, value: str):
        return value


@parse.with_pattern(r'(hello|world|foo|bar)')
@permutation(
    vector=(
        False,
        True,
    )
)
def parse_with_pattern_and_vector(text: str) -> str:
    return text


@parse.with_pattern(r'(alice|bob)')
def parse_with_pattern(text: str) -> str:
    return text


@parse.with_pattern('')
def parse_with_pattern_error(text: str) -> str:
    return text


def parse_enum_indirect(text: str) -> MessageDirection:
    return MessageDirection.from_string(text)
