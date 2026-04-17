from __future__ import annotations

from typing import Protocol

from age_bakeoff.models import ExtractionOutput


class Corpus(Protocol):
    name: str

    def load(self) -> ExtractionOutput: ...
