"""Strict untrusted parsing results, without database-controlled fields."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConstraintParseRequest(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


ClockTime = Annotated[str, Field(pattern=r"^[0-9]{2}:[0-9]{2}$")]
CalendarDate = Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


class ParsedTimeRuleProposal(StrictModel):
    kind: Literal["course", "protected"]
    title: Annotated[str, Field(min_length=1)]
    recurrence: Literal["weekly", "once"]
    weekday: Annotated[int, Field(ge=1, le=7)] | None
    date: CalendarDate | None
    start_time: ClockTime
    end_time: ClockTime


class ParsedResult(StrictModel):
    status: Literal["parsed"]
    proposal: ParsedTimeRuleProposal


class NeedsClarificationResult(StrictModel):
    status: Literal["needs_clarification"]
    message: Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]


class UnsupportedResult(StrictModel):
    status: Literal["unsupported"]
    message: Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]


ConstraintParseResult = Annotated[
    ParsedResult | NeedsClarificationResult | UnsupportedResult,
    Field(discriminator="status"),
]
RESULT_ADAPTER = TypeAdapter(ConstraintParseResult)
