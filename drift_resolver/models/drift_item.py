
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DriftClassification(str, Enum):

    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


class DriftItem(BaseModel):
    sql: str = Field(description="The raw SQL statement.")
    statement_type: str = Field(description="The normalized statement type.")
    table_name: str | None = Field(default=None, description="The affected table, if any.")
    column_name: str | None = Field(default=None, description="The affected column, if any.")
    classification: DriftClassification = Field(
        default=DriftClassification.UNKNOWN,
        description="The safety classification assigned to the statement.",
    )
    reason: str = Field(default="", description="Human-readable explanation for the classification.")
    auto_resolved: bool = Field(default=False, description="Whether the tool resolved the drift automatically.")
    rollback_sql: str | None = Field(
        default=None,
        description="SQL that can be used to roll back the drift statement.",
    )