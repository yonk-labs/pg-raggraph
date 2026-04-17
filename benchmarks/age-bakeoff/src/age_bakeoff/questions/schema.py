"""YAML loader + validator for the frozen question sets."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from age_bakeoff.models import Question, QuestionClass


class QuestionSet(BaseModel):
    corpus: str
    questions: list[Question]

    @field_validator("questions")
    @classmethod
    def _exactly_30(cls, v: list[Question]) -> list[Question]:
        if len(v) != 30:
            raise ValueError(f"Expected exactly 30 questions, got {len(v)}")
        bridging = sum(
            1 for q in v if q.question_class == QuestionClass.multi_hop_bridging
        )
        if bridging < 5:
            raise ValueError(
                f"Need >=5 multi_hop_bridging questions, got {bridging}"
            )
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate question IDs")
        return v


class _LooseQuestionSet(BaseModel):
    corpus: str
    questions: list[Question]


def load_question_set(
    path: str | Path, strict: bool = True
) -> QuestionSet | _LooseQuestionSet:
    raw = yaml.safe_load(Path(path).read_text())
    if strict:
        return QuestionSet.model_validate(raw)
    return _LooseQuestionSet.model_validate(raw)
