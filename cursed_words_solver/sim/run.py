"""Stage 5 — full-run simulation (shop + encounters)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cursed_words_solver.game_shop.recommendation import compute_shop_advice
from cursed_words_solver.models import Loadout, ShopState
from cursed_words_solver.shop_economy import can_afford, effective_purchase_price
from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.planner import EncounterPlanner, SearchAlgorithm
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


class RunPhase(str, Enum):
    ENCOUNTER = "encounter"
    SHOP = "shop"
    DONE = "done"


@dataclass
class RunResult:
    won: bool
    areas_cleared: int = 0
    money: int = 0
    phases: list[str] = field(default_factory=list)


@dataclass
class FullRunSimulator:
    """Simplified run loop: encounters + optional shop visits."""

    encounter_planner: EncounterPlanner | None = None
    encounter_engine: EncounterEngine | None = None
    max_encounters: int = 3

    def __post_init__(self) -> None:
        if self.encounter_planner is None:
            self.encounter_planner = EncounterPlanner()
        if self.encounter_engine is None:
            self.encounter_engine = EncounterEngine()

    def simulate_encounter(
        self,
        state: RunState,
        rng: SimRNG,
        *,
        plan_budget_sec: float = 15.0,
        algorithm: SearchAlgorithm = SearchAlgorithm.GREEDY,
    ) -> RunState:
        while not state.encounter_won and not state.encounter_lost:
            if state.grids_remaining <= 0 and state.encounter_remaining_target > 0:
                state.encounter_lost = True
                break

            plan = self.encounter_planner.plan(state, algorithm=algorithm, budget_sec=plan_budget_sec)
            if plan.submission is None:
                state.encounter_lost = True
                break

            step = self.encounter_engine.step(state, plan.submission, rng)
            state = step.state

        return state

    def simulate_shop(
        self,
        loadout: Loadout,
        shop: ShopState,
    ) -> Loadout:
        """Apply top shop advice buy when affordable (simplified Stage 5)."""
        advice = compute_shop_advice(loadout, shop)
        if not advice.buys:
            return loadout
        top = advice.buys[0]
        if top.offer_index is None or not (0 <= top.offer_index < len(shop.offers)):
            return loadout
        offer = shop.offers[top.offer_index]
        price = effective_purchase_price(offer, loadout, shop)
        if not can_afford(price, loadout):
            return loadout
        loadout.money -= price
        return loadout

    def simulate_run(
        self,
        initial: RunState,
        *,
        seed: int = 0,
        shop_states: list[ShopState] | None = None,
    ) -> RunResult:
        rng = SimRNG(root_seed=seed)
        state = initial.clone()
        shops = list(shop_states or [])
        result = RunResult(won=False, money=state.loadout.money)

        for enc in range(self.max_encounters):
            result.phases.append(RunPhase.ENCOUNTER.value)
            state = self.simulate_encounter(state, rng.with_step(enc))
            if state.encounter_lost:
                result.areas_cleared = enc
                result.money = state.loadout.money
                return result
            result.areas_cleared = enc + 1

            if enc < len(shops):
                result.phases.append(RunPhase.SHOP.value)
                state.loadout = self.simulate_shop(state.loadout, shops[enc])
                state.board.money = state.loadout.money

        result.won = state.encounter_won or result.areas_cleared >= self.max_encounters
        result.money = state.loadout.money
        result.phases.append(RunPhase.DONE.value)
        return result
