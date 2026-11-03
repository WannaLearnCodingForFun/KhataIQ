"""Parser registry: (bank, format) -> parser — YOU implement get_parser()."""

from __future__ import annotations

from khataiq.pipeline.parsers.base import Parser
from khataiq.pipeline.parsers.demo_csv import DemoBankCsvParser

ALL_PARSERS: list[Parser] = [DemoBankCsvParser()]


def get_parser(bank: str, fmt: str) -> Parser:
    """Return the parser registered for (bank, fmt). Matching ignores case.

    Unknown pair -> KeyError naming the pair.
    Think: why build a dict once instead of looping over ALL_PARSERS each call, and what
    should happen if two parsers ever register the same (bank, format)?
    """
    # TODO
    raise NotImplementedError
