from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionType(str, Enum):
    EXPEDITE = "EXPEDITE"
    REROUTE_LOT = "REROUTE_LOT"


class BaseAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action_id: str
    target_machine: str
    expires_at: Optional[float] = Field(default=None, ge=0.0)


class ExpediteParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_product: str
    ratio: float = Field(ge=0.0, le=1.0)
    max_priority_boost: int = Field(default=5, ge=0, le=20)


class RerouteParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_product: str
    ratio: float = Field(ge=0.0, le=1.0)
    destination_machine: str


class ExpediteAction(BaseAction):
    action_type: Literal[ActionType.EXPEDITE]
    parameters: ExpediteParameters


class RerouteAction(BaseAction):
    action_type: Literal[ActionType.REROUTE_LOT]
    parameters: RerouteParameters


ActionV1 = Union[ExpediteAction, RerouteAction]


class ActionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: ActionV1

    @model_validator(mode="after")
    def validate_ttl(self) -> "ActionEnvelope":
        return self
