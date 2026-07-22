from dataclasses import dataclass
from typing import Any, Protocol


class ParseError(ValueError):
    """The source cannot safely produce a current entity state."""


@dataclass(slots=True)
class ParseResult:
    parser_name: str
    parser_version: str
    entities: list[dict[str, Any]]
    warnings: list[str]


class Parser(Protocol):
    name: str
    version: str

    def parse(self, content: bytes, source_path: str) -> ParseResult: ...
