from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.snapshot_factory import RuntimeMachine, WorldState
from schemas.action_v1 import ActionType, ExpediteAction, RerouteAction


DispatchRule = Callable[[list], list]


@dataclass
class RuleHandle:
    machine_id: str
    original_rule: DispatchRule | None
    expires_at: float | None


class ActionInjector:
    def __init__(self) -> None:
        self._rule_registry: dict[str, RuleHandle] = {}

    def validate_machine(self, world: WorldState, machine_id: str) -> RuntimeMachine:
        machine = world.machines.get(machine_id)
        if machine is None:
            raise ValueError(f"target_machine does not exist: {machine_id}")
        return machine

    def inject(self, world: WorldState, action, now_sim_min: float, dispatch_rules: dict[str, DispatchRule]) -> None:
        machine = self.validate_machine(world, action.target_machine)
        if action.expires_at is not None and now_sim_min > action.expires_at:
            raise ValueError("action expired by TTL")

        if action.action_type == ActionType.EXPEDITE:
            self._inject_expedite(machine, action, dispatch_rules)
            return

        if action.action_type == ActionType.REROUTE_LOT:
            self._inject_reroute(machine, action, dispatch_rules)
            return

        raise ValueError(f"unsupported action_type: {action.action_type}")

    def rollback(self, machine_id: str, dispatch_rules: dict[str, DispatchRule]) -> None:
        handle = self._rule_registry.get(machine_id)
        if handle is None:
            return
        if handle.original_rule is not None:
            dispatch_rules[machine_id] = handle.original_rule
        self._rule_registry.pop(machine_id, None)

    def _inject_expedite(
        self,
        machine: RuntimeMachine,
        action: ExpediteAction,
        dispatch_rules: dict[str, DispatchRule],
    ) -> None:
        target_product = action.parameters.target_product
        ratio = action.parameters.ratio
        max_boost = action.parameters.max_priority_boost
        if ratio <= 0.0:
            raise ValueError("ratio must be > 0 for EXPEDITE")
        if max_boost > 20:
            raise ValueError("max_priority_boost exceeds allowed limit")

        prior_rule = dispatch_rules.get(machine.tool_id)

        def rule(queue: list) -> list:
            if not queue:
                return queue
            # Enforce total ordering with index fallback + aging.
            ranked = []
            for idx, item in enumerate(queue):
                product = getattr(item, "product", None) or item.get("product")
                arrival = float(getattr(item, "arrival_time", 0.0) if hasattr(item, "arrival_time") else item.get("arrival_time", 0.0))
                aging_score = -arrival
                is_target = 0 if product == target_product else 1
                boost = 0 if product == target_product else min(max_boost, 1)
                ranked.append((is_target, boost, aging_score, idx, item))
            ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
            return [x[-1] for x in ranked]

        dispatch_rules[machine.tool_id] = rule
        self._rule_registry[machine.tool_id] = RuleHandle(
            machine_id=machine.tool_id,
            original_rule=prior_rule,
            expires_at=action.expires_at,
        )

    def _inject_reroute(
        self,
        machine: RuntimeMachine,
        action: RerouteAction,
        dispatch_rules: dict[str, DispatchRule],
    ) -> None:
        _ = machine
        if action.parameters.ratio < 0.0 or action.parameters.ratio > 1.0:
            raise ValueError("ratio must be in [0,1] for REROUTE_LOT")
        # Reroute action is intentionally validated here; execution is runner-side.
