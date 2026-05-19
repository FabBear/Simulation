from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MachineState(str, Enum):
    IDLE = "IDLE"
    RUN = "RUN"
    DOWN = "DOWN"
    DOWN_PM = "DOWN_PM"
    DOWN_BM = "DOWN_BM"
    SETUP = "SETUP"


class LotStatus(str, Enum):
    QUEUE = "QUEUE"
    PROCESSING = "PROCESSING"
    TRANSPORT = "TRANSPORT"
    HOLD = "HOLD"


class LocationType(str, Enum):
    MACHINE_QUEUE = "MACHINE_QUEUE"
    MACHINE_PROCESS = "MACHINE_PROCESS"
    STOCKER = "STOCKER"
    TRANSIT = "TRANSIT"


class SnapshotMachine(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tool_id: str
    state: MachineState
    current_setup: Optional[str] = None
    busy_until_sim_min: float = Field(ge=0.0)
    down_until_sim_min: Optional[float] = Field(default=None, ge=0.0)
    current_lot_id: Optional[str] = None
    queue_lot_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_down_fields(self) -> "SnapshotMachine":
        if self.state in (MachineState.DOWN, MachineState.DOWN_PM, MachineState.DOWN_BM):
            if self.down_until_sim_min is None:
                raise ValueError("down_until_sim_min is required for DOWN states")
        return self


class SnapshotLot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    lot_id: str
    product: str
    route_id: str
    step_seq: int = Field(ge=0)
    status: LotStatus
    location_type: LocationType
    location_id: str
    arrival_time_sim_min: float = Field(ge=0.0)
    cqt_deadline_sim_min: Optional[float] = Field(default=None, ge=0.0)


class SnapshotV2(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    snapshot_version: str
    anchor_epoch_sec: float
    sim_now_min: float = Field(ge=0.0)
    machines: list[SnapshotMachine]
    lots: list[SnapshotLot]

    @model_validator(mode="after")
    def _cross_validate(self) -> "SnapshotV2":
        machine_ids = {m.tool_id for m in self.machines}
        lot_map = {l.lot_id: l for l in self.lots}

        for lot in self.lots:
            if lot.location_type in (LocationType.MACHINE_QUEUE, LocationType.MACHINE_PROCESS):
                if lot.location_id not in machine_ids:
                    raise ValueError(f"Unknown machine location_id: {lot.location_id}")
            if lot.status == LotStatus.PROCESSING and lot.location_type != LocationType.MACHINE_PROCESS:
                raise ValueError(f"PROCESSING lot must have MACHINE_PROCESS location_type: {lot.lot_id}")
            if lot.status == LotStatus.QUEUE and lot.location_type != LocationType.MACHINE_QUEUE:
                raise ValueError(f"QUEUE lot must have MACHINE_QUEUE location_type: {lot.lot_id}")

        for machine in self.machines:
            for lot_id in machine.queue_lot_ids:
                lot = lot_map.get(lot_id)
                if lot is None:
                    raise ValueError(f"queue_lot_ids references unknown lot: {lot_id}")
                if lot.status != LotStatus.QUEUE:
                    raise ValueError(f"queue lot must be QUEUE status: {lot_id}")
                if lot.location_type != LocationType.MACHINE_QUEUE or lot.location_id != machine.tool_id:
                    raise ValueError(f"queue lot location mismatch: {lot_id}")

            if machine.current_lot_id is not None:
                lot = lot_map.get(machine.current_lot_id)
                if lot is None:
                    raise ValueError(f"current_lot_id references unknown lot: {machine.current_lot_id}")
                if lot.status != LotStatus.PROCESSING:
                    raise ValueError(f"current lot must be PROCESSING: {machine.current_lot_id}")
                if lot.location_type != LocationType.MACHINE_PROCESS or lot.location_id != machine.tool_id:
                    raise ValueError(f"current lot location mismatch: {machine.current_lot_id}")

        return self
