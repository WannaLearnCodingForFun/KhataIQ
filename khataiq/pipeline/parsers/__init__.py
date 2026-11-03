"""Parser registry: (bank, format) -> parser."""

from __future__ import annotations

from khataiq.pipeline.parsers.base import Parser
from khataiq.pipeline.parsers.demo_csv import DemoBankCsvParser

ALL_PARSERS: list[Parser] = [DemoBankCsvParser()]


def _build_registry(parsers: list[Parser]) -> dict[tuple[str, str], Parser]:
    """Index parsers by lower-cased (bank, format). A duplicate key is a programming error,
    so it fails at import time rather than letting one parser silently shadow another."""
    registry: dict[tuple[str, str], Parser] = {}
    for parser in parsers:
        key = (parser.bank.lower(), parser.format.lower())
        if key in registry:
            raise RuntimeError(f"two parsers registered for {key}")
        registry[key] = parser
    return registry


_REGISTRY = _build_registry(ALL_PARSERS)


def get_parser(bank: str, fmt: str) -> Parser:
    """Return the parser registered for (bank, fmt). Matching ignores case.

    Unknown pair -> KeyError naming the pair.
    """
    try:
        return _REGISTRY[(bank.lower(), fmt.lower())]
    except KeyError:
        raise KeyError(f"no parser for bank={bank!r} format={fmt!r}") from None


def supported_parsers() -> list[tuple[str, str, str]]:
    """(bank, format, version) for every registered parser, sorted."""
    return sorted((p.bank, p.format, p.version) for p in ALL_PARSERS)
