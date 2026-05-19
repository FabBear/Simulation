from __future__ import annotations

import simpy
from dataclasses import dataclass, field

from schemas.snapshot_v2 import LocationType, LotStatus, SnapshotLot, SnapshotMachine, SnapshotV2


@dataclass
class RuntimeLot:
    lot_id: str
    product: str
    route_id: str
    step_seq: int
    arrival_time_sim_min: float
    cqt_deadline_sim_min: float | None
    status: LotStatus
    location_type: LocationType
    location_id: str


@dataclass
class RuntimeMachine:
    tool_id: str
    state: str
    current_setup: str | None
    busy_until_sim_min: float
    down_until_sim_min: float | None
    current_lot_id: str | None
    queue: list[RuntimeLot] = field(default_factory=list)

    def enqueue(self, lot: RuntimeLot) -> None:
        self.queue.append(lot)

    def resume_processing(self, lot: RuntimeLot) -> None:
        self.current_lot_id = lot.lot_id


@dataclass
class WorldState:
    snapshot: SnapshotV2
    machines: dict[str, RuntimeMachine]
    lots: dict[str, RuntimeLot]


class SnapshotFactory:
    @staticmethod
    def create_env_from_snapshot(snapshot: SnapshotV2) -> tuple[simpy.Environment, WorldState]:
        env = simpy.Environment(initial_time=snapshot.sim_now_min)
        machines = {
            m.tool_id: SnapshotFactory._machine_from_schema(m)
            for m in snapshot.machines
        }
        lots = {
            lot.lot_id: SnapshotFactory._lot_from_schema(lot)
            for lot in snapshot.lots
        }

        for lot in lots.values():
            if lot.location_type == LocationType.MACHINE_QUEUE:
                machine = machines.get(lot.location_id)
                if machine is None:
                    raise ValueError(f"Unknown location_id for queue lot: {lot.location_id}")
                machine.enqueue(lot)
            elif lot.location_type == LocationType.MACHINE_PROCESS:
                machine = machines.get(lot.location_id)
                if machine is None:
                    raise ValueError(f"Unknown location_id for processing lot: {lot.location_id}")
                machine.resume_processing(lot)

        world = WorldState(snapshot=snapshot, machines=machines, lots=lots)
        return env, world

    @staticmethod
    def _machine_from_schema(machine: SnapshotMachine) -> RuntimeMachine:
        return RuntimeMachine(
            tool_id=machine.tool_id,
            state=machine.state.value,
            current_setup=machine.current_setup,
            busy_until_sim_min=machine.busy_until_sim_min,
            down_until_sim_min=machine.down_until_sim_min,
            current_lot_id=machine.current_lot_id,
        )

    @staticmethod
    def _lot_from_schema(lot: SnapshotLot) -> RuntimeLot:
        return RuntimeLot(
            lot_id=lot.lot_id,
            product=lot.product,
            route_id=lot.route_id,
            step_seq=lot.step_seq,
            arrival_time_sim_min=lot.arrival_time_sim_min,
            cqt_deadline_sim_min=lot.cqt_deadline_sim_min,
            status=lot.status,
            location_type=lot.location_type,
            location_id=lot.location_id,
        )
