"""Owner-only natural language questions over the document library."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from answers.service import answer_question
from api.deps import require_owner

router = APIRouter(prefix="/api/ask", tags=["answers"], dependencies=[Depends(require_owner)])


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Literal["auto", "deep"] = "auto"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value):
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("Invalid question")
        return value


@router.post("")
def ask(request: Question):
    return answer_question(request.question, request.depth)
