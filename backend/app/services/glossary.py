"""Tenant glossary normalization that preserves raw transcript text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .persian import normalize_persian


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    term: str
    aliases: tuple[str, ...] = ()
    category: str = "general"

    def as_prompt_item(self) -> dict:
        return {"term": self.term, "aliases": list(self.aliases), "category": self.category}


def normalize_with_glossary(text: str, entries: list[GlossaryEntry]) -> str:
    normalized = normalize_persian(text)
    replacements: list[tuple[str, str]] = []
    for entry in entries:
        for alias in entry.aliases:
            alias_normalized = normalize_persian(alias)
            if alias_normalized:
                replacements.append((alias_normalized, entry.term))
    for alias, term in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(
            rf"(?<!\w){re.escape(alias)}(?!\w)", term, normalized, flags=re.IGNORECASE
        )
    return normalized


def apply_glossary(segments: list[dict], entries: list[GlossaryEntry]) -> list[dict]:
    return [
        {**item, "normalized_text": normalize_with_glossary(str(item.get("text", "")), entries)}
        for item in segments
    ]
