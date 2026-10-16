"""Full-run simulator: ``Game`` drives nodes and exposes a typed action API.

Phases (``Game.phase``):

- ``encounter``  submit / skip / reroll / place consumable / Twinkle Toes swap / sell /
                 reorder; ``michael_draft`` and ``forced_sell`` are encounter sub-states
- ``shop``       buy (sticker/stamp/tile) / hippo-feed / freeze / reroll / sell /
                 reorder / leave
- ``boss_draft`` pick one of the floor's bosses
- ``pin_reward`` upgrade the pin's left / right side (ID Card: both)
- ``done``       ``Game.won`` says how the run ended

Every rule comes from the decompiled game (see docs/game-research/sim-game.md).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cursed_words_solver.sim.game.challenges import ChallengeRun, make_challenge
from cursed_words_solver.sim.game.core import Rng, Tile
from cursed_words_solver.sim.game.encounter import Encounter, SubmitResult
from cursed_words_solver.sim.game.items import Item, make_item
from cursed_words_solver.sim.game.player import (
    ENCOUNTER_NODES,
    MICHAEL_STAGE,
    SHOP_NODES,
    Node,
    Player,
    resolve_character,
)
from cursed_words_solver.sim.game.shop import Shop, can_sell, sell_item

DEFAULT_UNLOCKED = frozenset({
    "WetDennis", "NinaNix", "HayleyBayles", "SamGambit", "BonesTheDog", "Octacles",
    "NathaServo", "PrismaticBean", "SandySaguaro", "SockHead", "Spike",
})


@dataclass
class RunConfig:
    character: str = "WetDennis"
    ascension: int = 0
    challenge: str | None = None
    seed: int | str = 0
    # Shop Advice starter item only appears before a character's first crown win.
    character_never_won: bool = False
    # Characters already unlocked: secret bosses only appear for locked ones.
    unlocked_characters: frozenset[str] = DEFAULT_UNLOCKED
    wordlist: Path | None = None


@dataclass
class Event:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class _Words:
    """``Vocabulary.GetRandomWord`` over the game word list (lazy)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._by_len: dict[int, list[str]] | None = None

    def _load(self) -> dict[int, list[str]]:
        if self._by_len is None:
            from cursed_words_solver.config import resolve_wordlist

            path = self.path or resolve_wordlist(None)
            by_len: dict[int, list[str]] = {}
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        w = line.strip().lower()
                        if w.isalpha():
                            by_len.setdefault(len(w), []).append(w)
            except OSError:
                pass
            self._by_len = by_len
        return self._by_len

    def random(self, rng: Rng, length: int) -> str | None:
        words = self._load().get(int(length))
        if not words:
            return None
        return words[rng.range(0, len(words))]


class Game:
    def __init__(self, config: RunConfig | None = None, **kw: Any) -> None:
        self.config = config or RunConfig(**kw)
        cfg = self.config
        self.rng = Rng(cfg.seed)
        challenge: ChallengeRun | None = make_challenge(cfg.challenge)
        character = challenge.character if challenge is not None and challenge.character else cfg.character
        ascension = 0 if challenge is not None else int(cfg.ascension)
        self.player = Player(resolve_character(character), ascension, challenge)
        self.words = _Words(cfg.wordlist)
        self.events: list[Event] = []
        self.encounter: Encounter | None = None
        self.shop: Shop | None = None
        self.won: bool | None = None
        self.end_reason = ""
        self._init_run()

    # -- setup ------------------------------------------------------------------

    def _init_run(self) -> None:
        """``GameStatics.InitialisePlayerForNewRun`` + ``GoToNextNodeAndGetSceneName``."""
        p, rng, run = self.player, self.rng, self.player.run
        p.set_character_items(rng)
        run.generate_boss_drafts(rng, p)
        ch = run.challenge
        if ch is not None:
            for t in ch.starting_tiles():
                p.add_tile(t)
            for i, cls in enumerate(ch.starting_items):
                it = make_item(cls)
                it.selling_prevented = cls != "NestEgg"
                p.add_item(it, rng)
                if i < len(ch.item_upgrades):
                    for _ in range(ch.item_upgrades[i]):
                        it.upgrade(0, rng=rng, player=p)
                        it.times_upgraded += 1
        if run.asc(4):
            for _ in range(2):
                p.add_item(make_item("StampPadlock"), rng)
        if run.asc(6):
            for _ in range(2):
                p.add_item(make_item("StickerPadlock"), rng)
        self._advance()

    def random_word(self, length: int) -> str | None:
        return self.words.random(self.rng, length)

    # -- node flow ---------------------------------------------------------------

    @property
    def phase(self) -> str:
        if self.won is not None:
            return "done"
        node = self.player.run.node
        if node in ENCOUNTER_NODES:
            return "encounter"
        if node in SHOP_NODES:
            return "shop"
        if node == Node.BOSS_DRAFT:
            return "boss_draft"
        if node == Node.BOSS_REWARD:
            return "pin_reward"
        return "done"

    def _advance(self) -> None:
        run = self.player.run
        node = run.advance(self.player, self.rng, set(self.config.unlocked_characters))
        self.events.append(Event("node", {"stage": run.stage, "node": node.name}))
        self.encounter = None
        self.shop = None
        if node in ENCOUNTER_NODES:
            self.encounter = Encounter(self)
            self.encounter.start()
            if self.encounter.lost:
                self._end(False, self.encounter.lost_reason)
        elif node in SHOP_NODES:
            self.shop = Shop(self.player, self.rng, character_never_won=self.config.character_never_won)

    def _end(self, won: bool, reason: str) -> None:
        self.won = won
        self.end_reason = reason
        self.events.append(Event("end", {"won": won, "reason": reason, "stage": self.player.run.stage}))

    def _after_encounter_action(self) -> None:
        enc = self.encounter
        if enc is None:
            return
        if enc.lost:
            self._end(False, enc.lost_reason or "out_of_grids")
        elif enc.run_won:
            self._end(True, "michael" if enc.michael is not None else "final_boss")
        elif enc.won:
            self._advance()

    # -- encounter actions -------------------------------------------------------------

    def submit(self, path: list[tuple[int, int]], words: list[str]) -> SubmitResult:
        enc = self._enc()
        res = enc.submit(path, words)
        self.events.append(Event("submit", {"words": res.words, "score": res.score, "remaining": res.remaining_target}))
        self._after_encounter_action()
        return res

    def skip(self) -> SubmitResult:
        res = self._enc().skip()
        self._after_encounter_action()
        return res

    def reroll_grid(self) -> bool:
        return self._enc().reroll()

    def place_consumable(self, rack_index: int, x: int, y: int) -> bool:
        return self._enc().place_consumable(rack_index, x, y)

    def twinkle_swap(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        return self._enc().twinkle_swap(a, b)

    def choose_michael_boss(self, index: int) -> None:
        self._enc().choose_michael_draft(index)

    def _enc(self) -> Encounter:
        if self.encounter is None:
            raise RuntimeError(f"not in an encounter (phase {self.phase})")
        return self.encounter

    # -- shop actions ---------------------------------------------------------------

    def _shop(self) -> Shop:
        if self.shop is None:
            raise RuntimeError(f"not in a shop (phase {self.phase})")
        return self.shop

    def buy(self, kind: str, index: int, *, hippo: bool = False) -> bool:
        if kind == "tile":
            return self._shop().buy_tile(index)
        return self._shop().buy(kind, index, hippo=hippo)

    def freeze(self, kind: str, index: int) -> bool:
        return self._shop().toggle_freeze(kind, index)

    def reroll_shop(self) -> bool:
        return self._shop().reroll()

    def leave_shop(self) -> None:
        self._shop().leave()
        self._advance()

    # -- inventory actions (shop or encounter) -------------------------------------------

    def sell(self, kind: str, slot: int) -> int | None:
        arr = self.player.stickers if kind == "sticker" else self.player.stamps
        if not (0 <= slot < 5) or arr[slot] is None:
            return None
        item = arr[slot]
        if self.shop is not None:
            return self.shop.sell(item)
        if self.encounter is not None:
            return self.encounter.sell(item)
        return sell_item(self.player, item, self.rng)

    def move(self, kind: str, src: int, dst: int) -> bool:
        return self.player.move_item(kind, src, dst)

    def discard_tile(self, rack_index: int) -> bool:
        if 0 <= rack_index < 10 and self.player.consumables[rack_index] is not None:
            self.player.consumables[rack_index] = None
            return True
        return False

    # -- boss draft / reward -----------------------------------------------------------

    def boss_options(self) -> list:
        run = self.player.run
        return list(run.boss_drafts[run.stage - 1].options) if self.phase == "boss_draft" else []

    def choose_boss(self, index: int) -> None:
        if self.phase != "boss_draft":
            raise RuntimeError("not drafting a boss")
        boss = self.boss_options()[index]
        p = self.player
        p.active_bosses = [boss]
        if not boss.cursed and not p.has_faced_uncursed_boss:
            p.has_faced_uncursed_boss = True
        self.events.append(Event("boss", {"boss": boss.game_class, "cursed": boss.cursed, "mod": boss.floor_mod}))
        self._advance()

    def pin_options(self) -> list[str]:
        p = self.player
        if p.pin is None or len(p.pin.components) < 2:
            return ["skip"]
        return ["left", "right", "both"] if p.unpacked_of("IDCard") else ["left", "right"]

    def upgrade_pin(self, choice: str) -> None:
        """``BossRewardController.TakeUpgrade*``."""
        if self.phase != "pin_reward":
            raise RuntimeError("no pin reward pending")
        p = self.player
        if choice not in self.pin_options():
            raise ValueError(choice)
        pin = p.pin
        if pin is not None and choice != "skip":
            if choice == "both":
                pin.upgrade(-1, True, rng=self.rng, player=p)
            elif choice == "left":
                pin.upgrade(0, rng=self.rng, player=p)
            else:
                pin.upgrade(1, rng=self.rng, player=p)
            if choice in ("left", "both"):
                left = next((s for s in p.stickers if s is not None and s.game_class == "LeftHumanHand"), None)
                if left is not None:
                    idx = p.stickers.index(left)
                    if idx > 0 and p.stickers[idx - 1] is not None:
                        p.stickers[idx - 1].is_hb_favourite_sticker = True
                        p.stickers[idx - 1].upgrade(0)
        self.events.append(Event("pin", {"choice": choice}))
        self._advance()

    def __repr__(self) -> str:  # pragma: no cover
        run = self.player.run
        return f"<Game {self.player.character} crown {run.ascension} stage {run.stage} {run.node.name} ${self.player.money} {self.phase}>"
