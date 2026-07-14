"""Installed classifier-label catalog used for controlled corrections."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_INDEX_PREFIX_RE = re.compile(r"^\s*\d+[\s,]+(.*)$")
_PAREN_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")
_MAX_RESULTS = 100


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class Taxon:
    common_name: str
    scientific: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "common_name": self.common_name,
            "scientific": self.scientific,
        }


class LabelCatalog:
    def __init__(self, taxa: list[Taxon]) -> None:
        unique: dict[str, Taxon] = {}
        for taxon in taxa:
            unique.setdefault(_normalize(taxon.common_name), taxon)
        self._by_common = unique
        self._taxa = sorted(
            unique.values(), key=lambda taxon: taxon.common_name.casefold()
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "LabelCatalog":
        taxa: list[Taxon] = []
        for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
            text = raw_line.strip()
            if not text:
                continue
            indexed = _INDEX_PREFIX_RE.match(text)
            if indexed:
                text = indexed.group(1).strip()
            if not text or "background" in text.casefold():
                continue
            parenthesized = _PAREN_RE.match(text)
            if parenthesized:
                scientific = parenthesized.group(1).strip() or None
                common = parenthesized.group(2).strip()
            else:
                common, scientific = text, None
            if common:
                taxa.append(Taxon(common_name=common, scientific=scientific))
        return cls(taxa)

    def search(self, query: str, limit: int = 20) -> list[Taxon]:
        needle = _normalize(query)
        bounded = max(0, min(int(limit), _MAX_RESULTS))
        matches = [
            taxon
            for taxon in self._taxa
            if needle in _normalize(taxon.common_name)
            or needle in _normalize(taxon.scientific or "")
        ]
        return matches[:bounded]

    def resolve(self, common_name: str) -> Taxon | None:
        return self._by_common.get(_normalize(common_name))
